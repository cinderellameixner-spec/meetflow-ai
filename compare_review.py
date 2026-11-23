"""Compare only the reviewer on identical fresh Pro drafts of the English corpus."""
import json
import math
import statistics
import time
from datetime import datetime, timezone
from functools import partial

from batch import CORPUS, OUT
from meetflow import AnalysisError, MODEL, REVIEW_MODEL, analyze, request_json, resolve_key, review_draft, test_connection

MODELS = (MODEL, REVIEW_MODEL)


def log(message):
    print(message, flush=True)


def save(path, data):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    pending.replace(path)


def times(values):
    if not values:
        return {}
    return {"median_s": round(statistics.median(values), 3),
            "p95_s": sorted(values)[math.ceil(.95 * len(values)) - 1]}


def main():
    rows = [json.loads(line) for line in CORPUS["en"].read_text("utf-8").splitlines() if line.strip()]
    key = resolve_key("")
    for model in MODELS:
        log(f"正在验证 {model} 的连接…")
        test_connection(key, model=model)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = OUT / (stamp + "-review-pair")
    folder.mkdir(parents=True)
    log(f"结果目录 {folder}")
    records = []
    for index, row in enumerate(rows):
        label = f"[{index + 1}/{len(rows)}] {row['id']}"
        path = folder / (row["id"] + ".json")
        record = {"id": row["id"], "review": {}}
        records.append(record)
        log(f"{label} 正在生成共用 Pro 初稿…")
        try:
            draft = analyze(row["text"], key, version="v3", fixed_chunking=True, crosscheck=False)
        except AnalysisError as exc:
            record["draft_error"] = str(exc)
            save(path, record)
            log(f"{label} 初稿失败，两个复核组均跳过。{exc}")
            continue
        record["draft"] = draft
        save(path, record)
        for model in (MODELS if index % 2 == 0 else reversed(MODELS)):
            log(f"{label} 正在用 {model} 复核…")
            start = time.perf_counter()
            output = review_draft(row["text"].strip(), draft["summary"], draft["tasks"], key,
                                  partial(request_json, model=model))
            seconds = round(time.perf_counter() - start, 3)
            record["review"][model] = {"seconds": seconds, "result": output}
            save(path, record)
            status = output.get("review_warning", "复核完成")
            log(f"{label} {model} {seconds:.2f} 秒，{status}")

    pairs = [r for r in records if len(r["review"]) == 2]
    successful_pairs = [r for r in pairs if all(
        "review_warning" not in v["result"] for v in r["review"].values())]
    report = {"planned": len(rows), "draft_failures": len(rows) - len(pairs),
              "paired": len(pairs), "both_reviews_ok": len(successful_pairs), "models": {}}
    for model in MODELS:
        report["models"][model] = {
            "reviews_ok": sum("review_warning" not in r["review"][model]["result"] for r in pairs),
            "review_time_all_attempts": times([r["review"][model]["seconds"] for r in pairs]),
            "review_time_paired_success": times([r["review"][model]["seconds"] for r in successful_pairs]),
            "draft_plus_review_paired_success": times([round(r["draft"]["elapsed"] +
                  r["review"][model]["seconds"], 3) for r in successful_pairs])}
    save(folder / "run.json", report)
    log(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except AnalysisError as exc:
        raise SystemExit(str(exc)) from None
