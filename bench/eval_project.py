#!/usr/bin/env python3
"""Score a project's steps (geth project new) against the known right steps of its scenario.

Usage: eval_project.py <project_dir> <scenario>  -> one JSON line
Scenarios (bench/bench_project.sh):
  sc_cells     PBMC 10x reads, cell types and markers   -> scrnaseq, then sc_downstream after it
  bulk_de      airway reads, dexamethasone response     -> rnaseq, then differentialabundance after it
  multiomics   yeast RNA-seq + ATAC-seq in one delivery  -> rnaseq on RNA/, atacseq on ATAC/, independent
  noref        yeast RNA-seq, no reference in delivery  -> Ensembl yeast genome (reference), rnaseq after it
                                                        (once the catalogue has that genome: rnaseq only)
  smallrna     human miRNA reads                         -> a gap naming nf-core/smrnaseq, no Geth pipeline
  kang_gap     a count matrix, DE per cell type, no lab -> gaps only (no pipeline step can take an .h5ad)
  kang_lab     the same with --lab                        -> one lab step on the delivery's .h5ad
"""
import glob
import json
import os
import sys


def steps_of(pdir):
    try:
        return json.load(open(os.path.join(pdir, "steps.json")))["steps"]
    except (OSError, ValueError, KeyError):
        return []


def pipelines(steps, name):
    return [s for s in steps if s.get("kind") == "pipeline" and s.get("pipeline") == name]


def after_ok(step, target):
    return bool(step) and bool(target) and target[0]["id"] in (step[0].get("after") or [])


def score(pdir, scenario):
    steps = steps_of(pdir)
    analyses = [s for s in steps if s.get("kind") in ("pipeline", "lab")]
    checks = {"steps_checked": bool(steps) and open(os.path.join(pdir, "steps_check.txt")).read().startswith("STEP CHECK: OK")
              if os.path.isfile(os.path.join(pdir, "steps_check.txt")) else False}
    if scenario == "sc_cells":
        count, cells = pipelines(steps, "scrnaseq"), pipelines(steps, "sc_downstream")
        checks.update(scrnaseq=len(count) == 1, sc_downstream_after_it=len(cells) == 1 and after_ok(cells, count),
                      nothing_else=len(analyses) == 2, no_download=not any(s.get("kind") == "reference" for s in steps))
    elif scenario == "bulk_de":
        bulk, de = pipelines(steps, "rnaseq"), pipelines(steps, "differentialabundance")
        q = (de[0].get("question", "") if de else "").lower()
        checks.update(rnaseq=len(bulk) == 1, de_after_it=len(de) == 1 and after_ok(de, bulk),
                      de_compares_dex_with_untreated="dex" in q and any(w in q for w in ("untreated", "control", "vehicle")),
                      nothing_else=len(analyses) == 2, no_download=not any(s.get("kind") == "reference" for s in steps))
    elif scenario == "multiomics":
        rna, atac = pipelines(steps, "rnaseq"), pipelines(steps, "atacseq")
        checks.update(rnaseq_on_RNA=len(rna) == 1 and str(rna[0].get("data", "")).rstrip("/").endswith("/RNA"),
                      atacseq_on_ATAC=len(atac) == 1 and str(atac[0].get("data", "")).rstrip("/").endswith("/ATAC"),
                      independent=not any(s.get("after") for s in rna + atac),
                      nothing_else=len(analyses) == 2, no_download=not any(s.get("kind") == "reference" for s in steps))
    elif scenario == "noref":
        ref = [s for s in steps if s.get("kind") == "reference"]
        rna = pipelines(steps, "rnaseq")
        if glob.glob(os.path.join(os.environ.get("GETH_REFERENCES", ""), "saccharomyces_cerevisiae_R64-1-1_ens*")):
            # a project has catalogued the genome since: the right plan uses it, without a download
            checks.update(no_download=not ref, rnaseq=len(rna) == 1, nothing_else=len(analyses) == 1)
        else:
            checks.update(yeast_genome=len(ref) == 1 and ref[0].get("species") == "saccharomyces_cerevisiae"
                          and ref[0].get("assembly") == "R64-1-1",
                          rnaseq_after_it=len(rna) == 1 and after_ok(rna, ref), nothing_else=len(analyses) == 1)
    elif scenario == "smallrna":
        gaps = [s for s in steps if s.get("kind") == "gap"]
        checks.update(gap_names_smrnaseq=any(str(s.get("nfcore", "")).replace("nf-core/", "") == "smrnaseq" for s in gaps),
                      no_pipeline=not analyses)
    elif scenario == "kang_gap":
        checks.update(gap=any(s.get("kind") == "gap" for s in steps), no_pipeline=not analyses)
    elif scenario == "kang_lab":
        lab = [s for s in steps if s.get("kind") == "lab"]
        checks.update(lab_step=len(lab) == 1 and not lab[0].get("after"), nothing_else=len(analyses) == 1)
    else:
        raise SystemExit(f"unknown scenario {scenario}")
    failed = [k for k, v in checks.items() if not v]
    return {"run": os.path.basename(pdir), "scenario": scenario, "score": f"{len(checks) - len(failed)}/{len(checks)}",
            "failed": failed, "steps": [f"{s.get('id')}:{s.get('kind')}:{s.get('pipeline') or s.get('species') or s.get('nfcore') or ''}"
                                         f"{'<' + ','.join(s['after']) if s.get('after') else ''}" for s in steps]}


if __name__ == "__main__":
    print(json.dumps(score(sys.argv[1], sys.argv[2])))
