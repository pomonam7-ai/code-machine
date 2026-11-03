"""여러 영상 일괄 처리: 폴더 펼치기 → 이미 편집된 영상 건너뛰기 → 하나씩 편집 → 결과 요약(CSV).

한 영상에서 오류가 나도 다음 영상으로 계속 진행합니다.
"""
import csv
import os
import re
import time
import traceback
import unicodedata

from .config import Config
from .pipeline import run, Logger

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
OUT_SUFFIX = "_편집본"
WORK_SUFFIX = "_autocut_work"


def _nfc(s):
    return unicodedata.normalize("NFC", s)


def _natural_key(path):
    """'강의2' < '강의10' 순서로 정렬."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", _nfc(path))]


def is_video(path):
    """편집 대상 영상인지. 결과물(_편집본)과 렌더링 중 임시 파일(.part)은 제외."""
    name = _nfc(os.path.basename(path))
    stem, ext = os.path.splitext(name)
    if ext.lower() not in VIDEO_EXTS:
        return False
    if stem.endswith(".part"):
        stem = stem[:-5]
    return not stem.endswith(OUT_SUFFIX)


def collect_inputs(paths, recursive=False):
    """파일/폴더 목록을 편집할 영상 목록 [(영상 경로, 폴더 기준 상대 하위폴더)]로 펼침.

    폴더를 주면 그 안의 영상을 모읍니다(recursive=True면 하위 폴더까지).
    작업 폴더(*_autocut_work)와 결과물(*_편집본.*)은 건너뜁니다.
    """
    items, seen, missing = [], set(), []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            found = []
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not _nfc(d).endswith(WORK_SUFFIX)) if recursive else []
                rel = os.path.relpath(root, p)
                rel = "" if rel == "." else rel
                found += [(os.path.join(root, f), rel) for f in files if is_video(f)]
            items += sorted(found, key=lambda x: (_natural_key(x[1]), _natural_key(os.path.basename(x[0]))))
        elif os.path.isfile(p):
            items.append((p, ""))
        else:
            missing.append(p)
    out = []
    for path, rel in items:
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            out.append((path, rel))
    return out, missing


def output_path_for(path, rel="", out_dir=None):
    """결과 파일 경로. out_dir이 없으면 원본 옆, 있으면 out_dir/하위폴더/에 저장."""
    stem = os.path.splitext(os.path.basename(path))[0] + OUT_SUFFIX + ".mp4"
    if out_dir:
        return os.path.join(os.path.abspath(out_dir), rel, stem)
    return os.path.join(os.path.dirname(path), stem)


EDITABLE = ("transcript.json", "illustrations.json", "pii.json")


def is_done(path, out):
    """결과 파일이 원본보다 나중에 만들어졌으면 이미 편집된 것으로 봄.
    단, 작업 폴더의 JSON(대본/일러스트/모자이크)을 결과 이후에 고쳤다면 다시 렌더링해야 하므로 False."""
    try:
        if os.path.getsize(out) <= 0:
            return False
        t_out = os.path.getmtime(out)
        if t_out < os.path.getmtime(path):
            return False
    except OSError:
        return False
    work = os.path.splitext(path)[0] + WORK_SUFFIX
    for name in EDITABLE:
        try:
            if os.path.getmtime(os.path.join(work, name)) > t_out:
                return False
        except OSError:
            pass
    return True


REPORT_FIELDS = [("input", "원본"), ("status", "상태"), ("output", "결과 파일"), ("minutes", "소요(분)"),
                 ("original", "원본 길이(초)"), ("kept", "편집본 길이(초)"), ("removed", "줄어든 시간(초)"),
                 ("fillers", "필러 제거"), ("illustrations", "일러스트"), ("mosaics", "모자이크"), ("error", "오류")]


def write_report(results, path):
    """엑셀에서 바로 열리도록 UTF-8(BOM) CSV로 저장."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([title for _, title in REPORT_FIELDS])
        for r in results:
            w.writerow([r.get(k, "") for k, _ in REPORT_FIELDS])
    return path


def run_batch(items, cfg=None, log=None, reuse=True, skip_done=True, out_dir=None, output=None,
              stop_flag=None, transcript_override=None, report_dir=None, on_file=None):
    """영상 목록을 차례로 편집하고 결과 목록을 돌려줍니다.

    items: collect_inputs()의 결과 [(경로, 상대 하위폴더)]
    output: 영상이 1개일 때만 쓰는 결과 파일 경로(-o)
    on_file(i, n, path): 각 영상 시작 시 호출 (GUI 표시용)
    결과 상태: 완료 / 건너뜀 / 실패 / 중지
    """
    cfg = cfg or Config()
    log = log or Logger()
    n = len(items)
    results = []
    t0 = time.time()
    stopped = False
    for i, (path, rel) in enumerate(items, 1):
        name = os.path.basename(path)
        out = output if (output and n == 1) else output_path_for(path, rel, out_dir)
        r = {"input": path, "output": out}
        if stop_flag and stop_flag():
            stopped = True
            break
        if n > 1:
            log(f"━━━━━━━━ [{i}/{n}] {name}")
        if on_file:
            on_file(i, n, path)
        if skip_done and is_done(path, out):
            log(f"  이미 편집된 영상이라 건너뜀 → {os.path.basename(out)} (다시 하려면 결과 파일 삭제 또는 '처음부터 다시')")
            r["status"] = "건너뜀"
            results.append(r)
            continue
        ts = time.time()
        try:
            res = run(path, out, cfg, log, reuse=reuse, transcript_override=transcript_override, stop_flag=stop_flag)
            st = res["stats"]
            r.update(status="완료", output=res["output"], original=round(st["original"], 1), kept=round(st["kept"], 1),
                     removed=round(st["removed"], 1), fillers=st["fillers_cut"],
                     illustrations=res["illustrations"], mosaics=res["mosaics"])
        except Exception as e:
            if stop_flag and stop_flag():
                r.update(status="중지", error=str(e))
                stopped = True
            else:
                r.update(status="실패", error=str(e))
                log(f"✖ 오류 ({name}): {e}")
                log(traceback.format_exc().rstrip())
                if n > 1:
                    log("  → 다음 영상으로 계속합니다.")
        r["minutes"] = round((time.time() - ts) / 60, 1)
        results.append(r)
        if stopped:
            break
    # 중지로 처리하지 못한 영상도 목록에 남김
    for path, rel in items[len(results):]:
        results.append({"input": path, "output": output_path_for(path, rel, out_dir), "status": "중지"})

    if n > 1:
        summarize(results, log, time.time() - t0)
        rdir = report_dir or out_dir or os.path.dirname(items[0][0])
        try:
            rp = write_report(results, os.path.join(rdir, time.strftime("오토컷_일괄처리_%Y%m%d_%H%M%S.csv")))
            log(f"  결과 요약 파일: {rp}")
        except OSError as e:
            log(f"  결과 요약 파일을 저장하지 못했습니다: {e}")
    return results


def summarize(results, log, seconds):
    cnt = {}
    for r in results:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    parts = [f"{k} {cnt[k]}개" for k in ("완료", "건너뜀", "실패", "중지") if cnt.get(k)]
    log("━━━━━━━━ 일괄 처리 결과")
    log(f"  전체 {len(results)}개: {', '.join(parts)}  (총 {seconds / 60:.1f}분)")
    for r in results:
        if r["status"] == "실패":
            log(f"  ✖ {os.path.basename(r['input'])}: {r.get('error', '')}")
