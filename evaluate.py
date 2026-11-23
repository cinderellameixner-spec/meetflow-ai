"""Collect model outputs and aggregate independent human review."""
import argparse
import json
import math
from pathlib import Path
from statistics import mean, median
import time

from meetflow import AnalysisError, analyze, local_environment_key, MAX_CHARS, TASK_VERSIONS

WEIGHTS = {"coverage": .3, "fidelity": .3, "conciseness": .3, "readability": .1}


def read_rows(path):
    with path.open(encoding="utf-8-sig") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if not rows:
        raise ValueError("文件为空。")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("会议 ID 重复。")
    return rows


def collect(source, output, version):
    rows = read_rows(source)
    if not local_environment_key():
        raise ValueError("命令行评测需要已启用本机密钥的工作目录和 DEEPSEEK_API_KEY。")
    for r in rows:
        if (not isinstance(r.get("text"), str) or not 0 < len(r["text"].strip()) <= MAX_CHARS or
                not isinstance(r.get("gold_tasks"), list) or
                any(not isinstance(t, str) or not t.strip() for t in r["gold_tasks"])):
            raise ValueError(f"{r['id']} 缺少有效的原文或人工标注待办。")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        for r in rows:
            start = time.perf_counter()
            try:
                result, error = analyze(r["text"], version=version), None
            except AnalysisError as exc:
                result, error = None, str(exc)
            record = {**r, "version": version, "result": result, "error": error,
                      "elapsed_s": round(time.perf_counter() - start, 4),
                      "matches": None if result else [], "ratings": dict.fromkeys(WEIGHTS)}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            print(r["id"], "OK" if result else error, flush=True)


def score(rows):
    tp = predicted = gold = passed = 0
    durations, ratings = [], []
    for r in rows:
        expected = r["gold_tasks"]
        gold += len(expected)
        if r["result"] is None:
            continue
        passed += 1
        tasks = r["result"]["tasks"]
        predicted += len(tasks)
        matches = r["matches"]
        scores = r["ratings"]
        if (not isinstance(matches, list) or any(not isinstance(pair, list) or len(pair) != 2 or
                any(type(i) is not int for i in pair) or not (1 <= pair[0] <= len(tasks) and
                1 <= pair[1] <= len(expected)) for pair in matches)):
            raise ValueError(f"{r['id']} 请填写有效的一对一匹配。")
        if any(len({p[i] for p in matches}) != len(matches) for i in (0, 1)):
            raise ValueError(f"{r['id']} 匹配重复。")
        if any(type(scores.get(k)) not in (int, float) or not 1 <= scores[k] <= 5 for k in WEIGHTS):
            raise ValueError(f"{r['id']} 请为四个摘要维度各打 1–5 分。")
        tp += len(matches)
        ratings.append(sum(scores[k] * weight for k, weight in WEIGHTS.items()))
        durations.append(r["elapsed_s"])
    durations.sort()
    return {"meetings": len(rows), "usable_outputs": passed, "TP": tp, "FP": predicted-tp,
            "FN": gold-tp, "precision": tp/predicted if predicted else None,
            "recall": tp/gold if gold else None, "final_format_pass_rate": passed/len(rows),
            "rated_summaries": len(ratings),
            "weighted_summary_score": round(mean(ratings), 3) if ratings else None,
            "median_s": median(durations) if durations else None,
            "p95_s": durations[math.ceil(.95*passed)-1] if durations else None,
            "max_s": max(durations, default=None),
            "all_meetings_under_3s": passed == len(rows) and max(durations, default=0) < 3}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    cmds = parser.add_subparsers(required=True, dest="cmd")
    run = cmds.add_parser("run")
    run.add_argument("dataset", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--version", choices=TASK_VERSIONS, default="v3")
    aggregate = cmds.add_parser("score")
    aggregate.add_argument("reviewed", type=Path)
    args = parser.parse_args()
    try:
        if args.cmd == "run":
            collect(args.dataset, args.output, args.version)
        else:
            print(json.dumps(score(read_rows(args.reviewed)), indent=2, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")

