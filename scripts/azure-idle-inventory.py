#!/usr/bin/env python3
"""
azure_idle_inventory.py  (read-only)

Inventories every resource in all Azure subscriptions you can access and flags
resources with no usage and no logs in the last N days (default 30), so they can
be documented before deletion.

Evidence collected per resource
  1. ARM metadata ........ type, kind, SKU, location, tags, createdTime, changedTime, managedBy
  2. Activity Log ........ control-plane events in the window (count, last time, caller, operation)
  3. Log Analytics ....... last record per _ResourceId in every workspace you can read
  4. Usage metric ........ one Azure Monitor metric per common resource type (requests, CPU, transactions...)
  5. Orphan rules ........ Resource Graph checks (unattached disks, unassociated IPs, empty plans, ...)
  6. Cost ................ actual cost per resource over the window (Cost Management)

The script makes NO changes. It only issues GET requests plus read-only POST queries
(Resource Graph, Log Analytics, Cost Management).

Requirements
  * Azure CLI signed in (az login). Azure Cloud Shell (Bash) already is.
  * Python 3.8+ (standard library only).
  * Roles: Reader on the subscriptions. Optional: Log Analytics Reader (workspace logs),
    Cost Management Reader (costs). Missing permissions are reported, not fatal.

Usage
  python3 azure_idle_inventory.py                       # all enabled subscriptions, 30 days
  python3 azure_idle_inventory.py --days 30 --subscriptions "Prod" 0000-...-id
  python3 azure_idle_inventory.py --skip-law --skip-cost   # faster run
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

ARM = "https://management.azure.com"
LA = "https://api.loganalytics.io"

WARNINGS = []
_warn_lock = threading.Lock()


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def warn(msg):
    with _warn_lock:
        WARNINGS.append(msg)
    log("WARN " + msg)


# --------------------------------------------------------------------------- auth / http

def az_json(args):
    p = subprocess.run(["az"] + args + ["-o", "json"], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"az {' '.join(args)} failed")
    return json.loads(p.stdout or "null")


_tokens = {}
_tok_lock = threading.Lock()


def token(resource, tenant=None, force=False):
    key = (resource, tenant)
    with _tok_lock:
        t = _tokens.get(key)
        if t and not force and t[1] - time.time() > 300:
            return t[0]
        args = ["account", "get-access-token", "--resource", resource]
        if tenant:
            args += ["--tenant", tenant]
        d = az_json(args)
        exp = d.get("expires_on")
        exp = float(exp) if exp else time.time() + 3000
        _tokens[key] = (d["accessToken"], exp)
        return d["accessToken"]


RETRY_HEADERS = (
    "Retry-After",
    "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-client-retry-after",
)


def http(method, url, body=None, resource=ARM, tenant=None, retries=7):
    data = json.dumps(body).encode() if body is not None else None
    force = False
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + token(resource, tenant, force))
        req.add_header("Content-Type", "application/json")
        force = False
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            if e.code == 401 and attempt == 0:
                force = True
                continue
            if e.code in (429, 500, 502, 503, 504):
                wait = None
                for h in RETRY_HEADERS:
                    v = e.headers.get(h)
                    if v:
                        try:
                            wait = float(v)
                            break
                        except ValueError:
                            pass
                time.sleep(min(90, wait if wait is not None else 2 ** attempt * 2))
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(2 ** attempt)
    raise RuntimeError(f"gave up after {retries} attempts: {url[:150]}")


def get_all(url, tenant=None):
    items = []
    while url:
        d = http("GET", url, tenant=tenant)
        items.extend(d.get("value", []))
        url = d.get("nextLink")
    return items


# --------------------------------------------------------------------------- helpers

def attribute(rid, known):
    """Map a (possibly child) resource ID to the closest known parent resource or RG ID."""
    if not rid:
        return None
    parts = rid.lower().rstrip("/").split("/")
    while len(parts) >= 5:
        cand = "/".join(parts)
        if cand in known:
            return cand
        parts = parts[:-2]
    return None


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- usage metrics
# type -> (metric name, aggregation). Value > 0 over the window means "in use".
USAGE_METRICS = {
    "microsoft.compute/virtualmachines": ("Percentage CPU", "Maximum"),
    "microsoft.compute/virtualmachinescalesets": ("Percentage CPU", "Maximum"),
    "microsoft.storage/storageaccounts": ("Transactions", "Total"),
    "microsoft.web/sites": ("Requests", "Total"),
    "microsoft.web/serverfarms": ("CpuPercentage", "Maximum"),
    "microsoft.sql/servers/databases": ("connection_successful", "Total"),
    "microsoft.sql/servers/elasticpools": ("cpu_percent", "Maximum"),
    "microsoft.dbforpostgresql/flexibleservers": ("active_connections", "Maximum"),
    "microsoft.dbformysql/flexibleservers": ("active_connections", "Maximum"),
    "microsoft.documentdb/databaseaccounts": ("TotalRequests", "Count"),
    "microsoft.cache/redis": ("connectedclients", "Maximum"),
    "microsoft.keyvault/vaults": ("ServiceApiHit", "Count"),
    "microsoft.containerregistry/registries": ("TotalPullCount", "Total"),
    "microsoft.containerservice/managedclusters": ("node_cpu_usage_percentage", "Maximum"),
    "microsoft.app/containerapps": ("Requests", "Total"),
    "microsoft.network/publicipaddresses": ("ByteCount", "Total"),
    "microsoft.network/loadbalancers": ("ByteCount", "Total"),
    "microsoft.network/applicationgateways": ("TotalRequests", "Total"),
    "microsoft.network/natgateways": ("ByteCount", "Total"),
    "microsoft.network/virtualnetworkgateways": ("AverageBandwidth", "Average"),
    "microsoft.network/azurefirewalls": ("DataProcessed", "Total"),
    "microsoft.eventhub/namespaces": ("IncomingMessages", "Total"),
    "microsoft.servicebus/namespaces": ("IncomingMessages", "Total"),
    "microsoft.cognitiveservices/accounts": ("TotalCalls", "Total"),
    "microsoft.logic/workflows": ("RunsStarted", "Total"),
    "microsoft.datafactory/factories": ("PipelineSucceededRuns", "Total"),
    "microsoft.apimanagement/service": ("Requests", "Total"),
    "microsoft.signalrservice/signalr": ("ConnectionCount", "Maximum"),
    "microsoft.search/searchservices": ("SearchQueriesPerSecond", "Maximum"),
    "microsoft.insights/components": ("requests/count", "Count"),
}


def metric_usage(rid, metric, agg, start, end, tenant):
    q = urllib.parse.urlencode({
        "api-version": "2018-01-01",
        "metricnames": metric,
        "timespan": f"{start}/{end}",
        "interval": "P1D",
        "aggregation": agg,
    })
    url = f"{ARM}{urllib.parse.quote(rid, safe='/')}/providers/Microsoft.Insights/metrics?{q}"
    d = http("GET", url, tenant=tenant)
    key = agg.lower()
    vals = [pt[key] for v in d.get("value", []) for ts in v.get("timeseries", [])
            for pt in ts.get("data", []) if pt.get(key) is not None]
    if not vals:
        return 0.0
    return max(vals) if key in ("maximum", "average") else sum(vals)


# --------------------------------------------------------------------------- orphan rules (Resource Graph)
ORPHAN_QUERIES = [
    ("Unattached managed disk",
     "resources | where type =~ 'microsoft.compute/disks' "
     "| where tostring(properties.diskState) =~ 'Unattached' and isempty(managedBy) | project id"),
    ("Public IP not associated with any resource",
     "resources | where type =~ 'microsoft.network/publicipaddresses' "
     "| where isnull(properties.ipConfiguration) and isnull(properties.natGateway) | project id"),
    ("NIC not attached to a VM or private endpoint",
     "resources | where type =~ 'microsoft.network/networkinterfaces' "
     "| where isnull(properties.virtualMachine) and isnull(properties.privateEndpoint) "
     "and isnull(properties.privateLinkService) | project id"),
    ("NSG not associated with any subnet or NIC",
     "resources | where type =~ 'microsoft.network/networksecuritygroups' "
     "| where coalesce(array_length(properties.subnets),0) == 0 "
     "and coalesce(array_length(properties.networkInterfaces),0) == 0 | project id"),
    ("VM deallocated or stopped",
     "resources | where type =~ 'microsoft.compute/virtualmachines' "
     "| extend ps = tostring(properties.extended.instanceView.powerState.code) "
     "| where ps in~ ('PowerState/deallocated','PowerState/stopped') | project id"),
    ("App Service plan with no apps",
     "resources | where type =~ 'microsoft.web/serverfarms' "
     "| where toint(properties.numberOfSites) == 0 | project id"),
    ("Web/Function app in Stopped state",
     "resources | where type =~ 'microsoft.web/sites' "
     "| where tostring(properties.state) =~ 'Stopped' | project id"),
    ("Load balancer with no backend pools",
     "resources | where type =~ 'microsoft.network/loadbalancers' "
     "| where coalesce(array_length(properties.backendAddressPools),0) == 0 | project id"),
    ("Route table not associated with any subnet",
     "resources | where type =~ 'microsoft.network/routetables' "
     "| where coalesce(array_length(properties.subnets),0) == 0 | project id"),
    ("NAT gateway not associated with any subnet",
     "resources | where type =~ 'microsoft.network/natgateways' "
     "| where coalesce(array_length(properties.subnets),0) == 0 | project id"),
    ("Private DNS zone with no VNet links",
     "resources | where type =~ 'microsoft.network/privatednszones' "
     "| where toint(properties.numberOfVirtualNetworkLinks) == 0 | project id"),
    ("Availability set with no VMs",
     "resources | where type =~ 'microsoft.compute/availabilitysets' "
     "| where coalesce(array_length(properties.virtualMachines),0) == 0 | project id"),
    ("Snapshot older than 90 days",
     "resources | where type =~ 'microsoft.compute/snapshots' "
     "| where todatetime(properties.timeCreated) < ago(90d) | project id"),
]


def graph(query, sub_ids, tenant):
    rows, skip = [], None
    url = f"{ARM}/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01"
    while True:
        opts = {"$top": 1000, "resultFormat": "objectArray"}
        if skip:
            opts["$skipToken"] = skip
        d = http("POST", url, {"subscriptions": sub_ids, "query": query, "options": opts}, tenant=tenant)
        rows.extend(d.get("data", []))
        skip = d.get("$skipToken")
        if not skip:
            return rows


# --------------------------------------------------------------------------- classification

def blank_row(**kw):
    row = {
        "recommendation": "", "reason": "",
        "subscription": "", "subscriptionId": "", "resourceGroup": "", "name": "", "type": "",
        "kind": "", "sku": "", "location": "", "createdTime": "", "changedTime": "",
        "activityEventsInWindow": 0, "lastActivity": "", "lastActivityCaller": "", "lastActivityOperation": "",
        "lawRecordsInWindow": 0, "lastLawRecord": "",
        "usageMetric": "", "usageValueInWindow": "",
        "orphanReason": "", "costInWindow": "", "currency": "",
        "tags": "", "managedBy": "", "resourceId": "",
    }
    row.update(kw)
    return row


def classify(r):
    """Return (recommendation, reason) for one row."""
    has_logs = r["activityEventsInWindow"] > 0 or r["lawRecordsInWindow"] > 0
    usage = r["usageValueInWindow"]           # float, or "" if not applicable / unknown
    metric_ok = isinstance(usage, float)
    used = metric_ok and usage > 0
    orphan = r["orphanReason"]

    if orphan and not used:
        return "DELETE CANDIDATE", f"Orphaned: {orphan}" + ("; has log activity, check caller" if has_logs else "")
    if orphan and used:
        return "REVIEW", f"Orphan rule matched ({orphan}) but usage metric > 0"
    if metric_ok and not used and not has_logs:
        return "DELETE CANDIDATE", "No usage metric activity and no logs in window"
    if metric_ok and not used and has_logs:
        return "REVIEW", "Usage metric is zero but control-plane/log activity exists"
    if not metric_ok and not has_logs:
        return "REVIEW", "No logs in window; no usage metric for this type (check dependencies)"
    return "KEEP", "Active in window"


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Read-only Azure idle-resource inventory")
    ap.add_argument("--days", type=int, default=30, help="look-back window in days (default 30, max 90 for Activity Log)")
    ap.add_argument("--subscriptions", nargs="*", help="limit to these subscription IDs or names")
    ap.add_argument("--skip-metrics", action="store_true")
    ap.add_argument("--skip-law", action="store_true", help="skip Log Analytics workspace queries")
    ap.add_argument("--skip-cost", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=".", help="output directory")
    a = ap.parse_args()

    end_dt = datetime.now(timezone.utc).replace(microsecond=0)
    start_dt = end_dt - timedelta(days=a.days)
    start, end = iso(start_dt), iso(end_dt)
    stamp = end_dt.strftime("%Y%m%d-%H%M")
    os.makedirs(a.out, exist_ok=True)

    # ---- subscriptions
    subs = [s for s in az_json(["account", "list", "--all"]) if s.get("state") == "Enabled"]
    if a.subscriptions:
        want = {x.lower() for x in a.subscriptions}
        subs = [s for s in subs if s["id"].lower() in want or s["name"].lower() in want]
    seen, uniq = set(), []
    for s in subs:
        if s["id"] not in seen:
            seen.add(s["id"])
            uniq.append(s)
    subs = uniq
    if not subs:
        sys.exit("No enabled subscriptions found. Run 'az login' first.")
    sub_name = {s["id"].lower(): s["name"] for s in subs}
    sub_tenant = {s["id"].lower(): s.get("tenantId") for s in subs}
    log(f"{len(subs)} subscription(s); window {start} to {end}")

    # ---- inventory
    resources, rgs = {}, {}

    def inv(s):
        sid, t = s["id"], s.get("tenantId")
        res = get_all(f"{ARM}/subscriptions/{sid}/resources?api-version=2021-04-01&$expand=createdTime,changedTime", t)
        grp = get_all(f"{ARM}/subscriptions/{sid}/resourcegroups?api-version=2021-04-01", t)
        return s, res, grp

    with ThreadPoolExecutor(a.workers) as ex:
        for fut in as_completed([ex.submit(inv, s) for s in subs]):
            try:
                s, res, grp = fut.result()
            except Exception as e:
                warn(f"inventory failed: {e}")
                continue
            for r in res:
                resources[r["id"].lower()] = r
            for g in grp:
                rgs[g["id"].lower()] = g
            log(f"  {s['name']}: {len(res)} resources, {len(grp)} resource groups")

    known = set(resources) | set(rgs)
    rows = {}
    for key, r in resources.items():
        parts = r["id"].split("/")
        sid = parts[2].lower()
        sku = r.get("sku") or {}
        rows[key] = blank_row(
            subscription=sub_name.get(sid, sid), subscriptionId=parts[2],
            resourceGroup=parts[4] if len(parts) > 4 else "",
            name=r.get("name", ""), type=r.get("type", "").lower(), kind=r.get("kind", "") or "",
            sku=" ".join(str(x) for x in (sku.get("name"), sku.get("tier")) if x),
            location=r.get("location", ""),
            createdTime=r.get("createdTime", "") or "", changedTime=r.get("changedTime", "") or "",
            tags=json.dumps(r["tags"], ensure_ascii=False) if r.get("tags") else "",
            managedBy=r.get("managedBy", "") or "", resourceId=r["id"])

    # empty resource groups
    rg_with_res = {"/".join(k.split("/")[:5]) for k in resources}
    empty = 0
    for key, g in rgs.items():
        if key in rg_with_res:
            continue
        empty += 1
        parts = g["id"].split("/")
        sid = parts[2].lower()
        rows[key] = blank_row(
            subscription=sub_name.get(sid, sid), subscriptionId=parts[2], resourceGroup=g["name"],
            name=g["name"], type="microsoft.resources/resourcegroups", location=g.get("location", ""),
            orphanReason="Empty resource group", resourceId=g["id"],
            tags=json.dumps(g["tags"], ensure_ascii=False) if g.get("tags") else "",
            managedBy=g.get("managedBy", "") or "")
    log(f"inventory: {len(resources)} resources, {empty} empty resource groups")

    # ---- activity log
    flt = urllib.parse.quote(f"eventTimestamp ge '{start}' and eventTimestamp le '{end}'")
    sel = "eventTimestamp,resourceId,caller,operationName"
    act_lock = threading.Lock()

    def activity(s):
        url = (f"{ARM}/subscriptions/{s['id']}/providers/Microsoft.Insights/eventtypes/management/values"
               f"?api-version=2015-04-01&$filter={flt}&$select={sel}")
        n = 0
        while url:
            d = http("GET", url, tenant=s.get("tenantId"))
            with act_lock:
                for ev in d.get("value", []):
                    k = attribute(ev.get("resourceId"), known)
                    if not k or k not in rows:
                        continue
                    row = rows[k]
                    row["activityEventsInWindow"] += 1
                    ts = ev.get("eventTimestamp", "")
                    if ts > row["lastActivity"]:
                        row["lastActivity"] = ts
                        row["lastActivityCaller"] = ev.get("caller", "") or ""
                        row["lastActivityOperation"] = (ev.get("operationName") or {}).get("value", "")
                    n += 1
            url = d.get("nextLink")
        return s, n

    with ThreadPoolExecutor(min(a.workers, 4)) as ex:
        for fut in as_completed([ex.submit(activity, s) for s in subs]):
            try:
                s, n = fut.result()
                log(f"  activity log {s['name']}: {n} events")
            except Exception as e:
                warn(f"activity log failed: {e}")

    # ---- resource graph: orphans + workspaces
    by_tenant = defaultdict(list)
    for s in subs:
        by_tenant[s.get("tenantId")].append(s["id"])
    workspaces = []
    for t, ids in by_tenant.items():
        for reason, q in ORPHAN_QUERIES:
            try:
                for hit in graph(q, ids, t):
                    k = hit["id"].lower()
                    if k in rows:
                        rows[k]["orphanReason"] = "; ".join(x for x in (rows[k]["orphanReason"], reason) if x)
            except Exception as e:
                warn(f"orphan rule '{reason}' failed: {e}")
        if not a.skip_law:
            try:
                workspaces += [(w, t) for w in graph(
                    "resources | where type =~ 'microsoft.operationalinsights/workspaces' "
                    "| project id, name, customerId = tostring(properties.customerId)", ids, t)]
            except Exception as e:
                warn(f"workspace discovery failed: {e}")
    log(f"orphan rules matched {sum(1 for r in rows.values() if r['orphanReason'])} items")

    # ---- log analytics
    if not a.skip_law and workspaces:
        kql = (f"union withsource=_T * | where TimeGenerated > ago({a.days}d) | where isnotempty(_ResourceId) "
               f"| summarize last = max(TimeGenerated), n = count() by rid = tolower(_ResourceId)")

        def law(wt):
            w, t = wt
            d = http("POST", f"{LA}/v1/workspaces/{w['customerId']}/query",
                     {"query": kql, "timespan": f"P{a.days}D"}, resource=LA, tenant=t)
            tbl = (d.get("tables") or [{}])[0]
            cols = [c["name"] for c in tbl.get("columns", [])]
            return w, [dict(zip(cols, row)) for row in tbl.get("rows", [])]

        with ThreadPoolExecutor(min(a.workers, 4)) as ex:
            for fut in as_completed([ex.submit(law, wt) for wt in workspaces]):
                try:
                    w, recs = fut.result()
                except Exception as e:
                    warn(f"Log Analytics query failed: {e}")
                    continue
                for rec in recs:
                    k = attribute(rec.get("rid"), known)
                    if k and k in rows:
                        rows[k]["lawRecordsInWindow"] += int(rec.get("n") or 0)
                        last = str(rec.get("last") or "")
                        if last > rows[k]["lastLawRecord"]:
                            rows[k]["lastLawRecord"] = last
                log(f"  workspace {w['name']}: {len(recs)} source resources")

    # ---- usage metrics
    if not a.skip_metrics:
        targets = [k for k, r in rows.items() if r["type"] in USAGE_METRICS
                   and not (r["type"] == "microsoft.sql/servers/databases" and r["name"].lower() == "master")]
        log(f"querying usage metrics for {len(targets)} resources")

        def met(k):
            r = rows[k]
            m, agg = USAGE_METRICS[r["type"]]
            return k, m, agg, metric_usage(r["resourceId"], m, agg, start, end, sub_tenant.get(r["subscriptionId"].lower()))

        done = 0
        with ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(met, k): k for k in targets}
            for fut in as_completed(futs):
                k = futs[fut]
                m, agg = USAGE_METRICS[rows[k]["type"]]
                rows[k]["usageMetric"] = f"{m} ({agg})"
                try:
                    _, _, _, v = fut.result()
                    rows[k]["usageValueInWindow"] = float(v)
                except Exception as e:
                    rows[k]["usageMetric"] += " [error]"
                    if len(WARNINGS) < 200:
                        warn(f"metric {m} on {rows[k]['name']}: {str(e)[:160]}")
                done += 1
                if done % 100 == 0:
                    log(f"  metrics {done}/{len(targets)}")

    # ---- cost
    if not a.skip_cost:
        body = {"type": "ActualCost", "timeframe": "Custom", "timePeriod": {"from": start, "to": end},
                "dataset": {"granularity": "None",
                            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                            "grouping": [{"type": "Dimension", "name": "ResourceId"}]}}
        for s in subs:
            url = f"{ARM}/subscriptions/{s['id']}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
            try:
                total = 0.0
                while url:
                    d = http("POST", url, body, tenant=s.get("tenantId"))
                    p = d.get("properties", {})
                    cols = [c["name"] for c in p.get("columns", [])]
                    ci = next((i for i, c in enumerate(cols) if "cost" in c.lower()), None)
                    ri = cols.index("ResourceId") if "ResourceId" in cols else None
                    cu = cols.index("Currency") if "Currency" in cols else None
                    for row in p.get("rows", []):
                        if ci is None or ri is None:
                            break
                        k = attribute(row[ri], known)
                        if k and k in rows:
                            prev = rows[k]["costInWindow"] or 0.0
                            rows[k]["costInWindow"] = round(prev + float(row[ci] or 0), 2)
                            rows[k]["currency"] = row[cu] if cu is not None else ""
                        total += float(row[ci] or 0)
                    url = p.get("nextLink")
                log(f"  cost {s['name']}: {total:,.2f}")
            except Exception as e:
                warn(f"cost query failed for {s['name']}: {str(e)[:200]}")

    # ---- classify + write
    for r in rows.values():
        r["recommendation"], r["reason"] = classify(r)

    order = {"DELETE CANDIDATE": 0, "REVIEW": 1, "KEEP": 2}
    out_rows = sorted(rows.values(), key=lambda r: (order[r["recommendation"]], r["subscription"],
                                                    r["resourceGroup"].lower(), r["type"], r["name"].lower()))
    fields = list(out_rows[0].keys()) if out_rows else []
    all_path = os.path.join(a.out, f"azure_inventory_{stamp}.csv")
    del_path = os.path.join(a.out, f"azure_delete_candidates_{stamp}.csv")
    for path, data in ((all_path, out_rows),
                       (del_path, [r for r in out_rows if r["recommendation"] == "DELETE CANDIDATE"])):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(data)

    def cost_sum(rs):
        return round(sum(r["costInWindow"] or 0 for r in rs if isinstance(r["costInWindow"], float)), 2)

    summary = {
        "generatedUtc": end, "windowStartUtc": start, "windowDays": a.days,
        "subscriptions": [{"id": s["id"], "name": s["name"]} for s in subs],
        "counts": dict(Counter(r["recommendation"] for r in out_rows)),
        "costInWindowByRecommendation": {k: cost_sum([r for r in out_rows if r["recommendation"] == k]) for k in order},
        "deleteCandidatesByType": dict(Counter(r["type"] for r in out_rows if r["recommendation"] == "DELETE CANDIDATE").most_common()),
        "skipped": {"metrics": a.skip_metrics, "logAnalytics": a.skip_law, "cost": a.skip_cost},
        "workspacesQueried": len(workspaces),
        "warnings": WARNINGS[:200],
    }
    sum_path = os.path.join(a.out, f"azure_inventory_summary_{stamp}.json")
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("done")
    print(json.dumps(summary["counts"], indent=2))
    print(f"\nFiles:\n  {all_path}\n  {del_path}\n  {sum_path}")


if __name__ == "__main__":
    main()