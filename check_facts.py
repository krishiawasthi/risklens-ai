"""Diagnostic: show what SEC's companyfacts holds for one filing.
Usage: python check_facts.py TSM 20-F
Prints taxonomies, units and tags for the latest filing of that form,
so we can see why financial values were or were not found."""
import sys
from collections import Counter

from dotenv import load_dotenv

from utils.sec_client import SECClient
from utils.xbrl import TAXONOMIES, detect_basis

load_dotenv()
ticker = sys.argv[1] if len(sys.argv) > 1 else "TSM"
form = sys.argv[2] if len(sys.argv) > 2 else "20-F"

sec = SECClient()
cik, name = sec.lookup_ticker(ticker)
filing = sec.latest_filing(cik, form, company=name)
print(f"{name}  CIK {cik}  {filing.form}  accession {filing.accession}  period {filing.period_end}")

cf = sec.company_facts(cik)
facts = cf.get("facts", {})
print("\nTaxonomies in companyfacts:", list(facts))

for tax, tags in facts.items():
    units_all, units_this, tags_this = Counter(), Counter(), set()
    accns = Counter()
    for tag, body in tags.items():
        for unit, rows in body.get("units", {}).items():
            units_all[unit] += len(rows)
            for r in rows:
                accns[r.get("accn")] += 1
                if r.get("accn") == filing.accession:
                    units_this[unit] += 1
                    tags_this.add(tag)
    print(f"\n[{tax}] {len(tags)} tags")
    print("  units (all filings):", dict(units_all.most_common(6)))
    print("  facts in THIS filing:", sum(units_this.values()), dict(units_this))
    print("  newest accessions:", [a for a, _ in sorted(accns.items(), key=lambda x: x[0] or "")[-5:]])
    wanted = {t for lst in TAXONOMIES.get(tax, {}).values() for t in lst}
    if wanted:
        present = sorted(wanted & set(tags))
        print("  RiskLens tags present at all:", present)
        print("  RiskLens tags missing:", sorted(wanted - set(tags)))
        print("  RiskLens tags in THIS filing:", sorted(wanted & tags_this))

print("\ndetect_basis ->", detect_basis(cf, filing.accession))
