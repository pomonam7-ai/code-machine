"""대본을 읽고 '설명이 필요한 순간'을 골라 어떤 일러스트를 넣을지 계획합니다.
- rules : 한국어 키워드 + 설명 신호어 기반 (항상 동작)
- ollama: 로컬 LLM(무료·오프라인)으로 문맥을 이해해 선택 (설치되어 있을 때만)"""
import json
import re
import urllib.request

from .illustrate import ICONS, list_logos

# 설명/개념 전달 신호어 → 일러스트가 이해에 도움 되는 문장
CUES = ["즉", "예를 들어", "예를 들면", "예컨대", "왜냐하면", "그래서", "핵심", "중요한", "정리하면", "요약하면",
        "원리", "개념", "이란", "라는 건", "라는 것은", "차이", "비교", "방법", "단계", "첫 번째", "두 번째", "세 번째",
        "결론", "포인트", "비유", "말하자면", "쉽게 말해"]
PARTICLES = ["에서는", "으로는", "에서", "으로", "에게", "까지", "부터", "처럼", "보다", "이라", "라는", "이란", "란",
             "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "만", "로", "랑", "이나", "나", "요"]


def _strip_particle(tok):
    tok = re.sub(r"[^\w가-힣%]", "", tok)
    for p in PARTICLES:
        if tok.endswith(p) and len(tok) - len(p) >= 1:
            return tok[: -len(p)]
    return tok


def _match(text):
    """문장 → [(concept, score, label)]"""
    # '왜냐하면'은 이유를 대는 말이지 질문이 아니므로 '왜'로 잡히지 않게 뺌
    text = re.sub(r"왜냐(하)?면", " ", text)
    res = []
    toks = text.split()
    for key, (_, default_label, stems) in ICONS.items():
        score, label = 0, None
        for st in stems:
            verb = st.endswith("*")
            st0 = st.rstrip("*")
            if st0.lower() in text.lower():
                score += 1
                if label is None:
                    if verb or len(st0) == 1:
                        label = default_label
                    else:
                        tok = next((t for t in toks if st0 in t), st0)
                        lab = _strip_particle(tok)
                        label = lab if st0 in lab and len(lab) <= 6 else st0
        if score:
            res.append((key, score, label if label is not None else default_label))
    res.sort(key=lambda x: -x[1])
    return res


def _first_pos(text, key):
    pos = [text.find(st.rstrip("*")) for st in ICONS[key][2] if st.rstrip("*") in text]
    return min(pos) if pos else 1 << 30


def sentences_from(segments):
    """위스퍼 세그먼트를 문장 단위로 (너무 짧은 건 다음과 합침)."""
    out = []
    buf = None
    for s in segments:
        if buf is None:
            buf = dict(start=s["start"], end=s["end"], text=s["text"])
        else:
            buf["end"] = s["end"]; buf["text"] += " " + s["text"]
        if buf["end"] - buf["start"] >= 1.8 or re.search(r"[.?!]$", buf["text"]):
            out.append(buf); buf = None
    if buf:
        out.append(buf)
    return out


def _pick(cands, total, cfg):
    """점수 높은 순으로 고르되 최소 간격 유지."""
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for c in cands:
        if all(abs(c["start"] - p["start"]) >= cfg.illu_min_gap for p in picked):
            picked.append(c)
    picked.sort(key=lambda c: c["start"])
    for c in picked:
        dur = min(cfg.illu_max_dur, max(cfg.illu_min_dur, c["end"] - c["start"]))
        c["end"] = min(total, c["start"] + dur)
    return picked


def logo_candidates(sents, cfg):
    """대본에 로고 이름(또는 별칭)이 나오면 그 문장에 로고를 띄울 후보로 추가. 직접 언급이라 점수를 높게 줌."""
    if not getattr(cfg, "use_logos", True):
        return []
    logos = list_logos(cfg.logo_dir or None)
    cands = []
    for s in sents:
        low = s["text"].lower()
        for name, info in logos.items():
            if any(k.lower() in low for k in info["keywords"]):
                cands.append(dict(start=s["start"], end=s["end"], score=6.0, concepts=[], logo=name,
                                  label="", text=s["text"], subject_en=""))
                break
    return cands


def plan_rules(sents, total, cfg, extra=()):
    cands = []
    for i, s in enumerate(sents):
        m = _match(s["text"])
        if not m:
            continue
        cue = sum(1 for q in CUES if q in s["text"])
        score = m[0][1] + 1.5 * cue + (0.5 if len(m) > 1 else 0)
        top = [m[0]] + ([m[1]] if len(m) > 1 and m[1][1] >= m[0][1] * 0.5 else [])
        # 두 개념이면 문장에 나온 순서대로 A → B
        top.sort(key=lambda x: _first_pos(s["text"], x[0]))
        concepts = [x[0] for x in top]
        label = m[0][2]
        if len(top) == 2 and top[0][2] and top[1][2] and top[0][2] != top[1][2] \
                and len(top[0][2]) + len(top[1][2]) + 1 <= cfg.max_label_chars:
            label = f"{top[0][2]}→{top[1][2]}"
        cands.append(dict(start=s["start"], end=s["end"], score=score, concepts=concepts,
                          label=label[: cfg.max_label_chars], text=s["text"], subject_en=""))
    return _pick(cands + list(extra), total, cfg)


def ollama_available(cfg):
    try:
        with urllib.request.urlopen(cfg.ollama_url + "/api/tags", timeout=2) as r:
            tags = json.load(r)
        names = [m["name"] for m in tags.get("models", [])]
        return any(n.startswith(cfg.ollama_model.split(":")[0]) for n in names)
    except Exception:
        return False


def plan_ollama(sents, total, cfg, log, extra=()):
    concept_desc = ", ".join(f"{k}({v[1] or v[2][0]})" for k, v in ICONS.items())
    lines = "\n".join(f"{i}. [{s['start']:.0f}s] {s['text']}" for i, s in enumerate(sents))
    max_n = max(1, int(total / cfg.illu_min_gap))
    prompt = f"""당신은 유튜브 영상 편집자입니다. 아래는 영상 대본(번호. [시간] 문장)입니다.
시청자의 이해를 돕기 위해 설명 일러스트를 넣으면 좋은 문장을 최대 {max_n}개 고르세요.
개념 설명, 비교, 숫자/변화, 단계, 핵심 강조 문장이 우선입니다. 인사·잡담은 제외합니다.
각 항목에 대해:
- idx: 문장 번호
- concepts: 아래 목록에서 1~2개 (2개면 A→B 관계로 그려짐)
- label: 화면에 쓸 한국어 키워드 1개 ({cfg.max_label_chars}글자 이하, 없어도 됨)
- subject_en: 그림 내용을 영어 한 문장으로 (예: "coins growing into a tall stack")
개념 목록: {concept_desc}

대본:
{lines}

JSON으로만 답하세요: {{"items":[{{"idx":0,"concepts":["money"],"label":"복리","subject_en":"..."}}]}}"""
    body = json.dumps({"model": cfg.ollama_model, "prompt": prompt, "format": "json", "stream": False,
                       "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request(cfg.ollama_url + "/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.load(r)["response"]
    items = json.loads(resp).get("items", [])
    cands = []
    for it in items:
        try:
            s = sents[int(it["idx"])]
        except Exception:
            continue
        concepts = [c for c in it.get("concepts", []) if c in ICONS][:2]
        if not concepts:
            m = _match(s["text"])
            concepts = [m[0][0]] if m else ["idea"]
        label = str(it.get("label") or "")[: cfg.max_label_chars]
        cands.append(dict(start=s["start"], end=s["end"], score=10 - len(cands) * 0.01, concepts=concepts,
                          label=label, text=s["text"], subject_en=str(it.get("subject_en") or "")))
    log(f"  로컬 LLM이 {len(cands)}개 장면을 제안했어요")
    return _pick(cands + list(extra), total, cfg)


def plan(segments, total, cfg, log):
    sents = sentences_from(segments)
    logos = logo_candidates(sents, cfg)
    if logos:
        log(f"  로고 언급 {len(logos)}곳 발견")
    use = cfg.planner
    if use == "auto":
        use = "ollama" if ollama_available(cfg) else "rules"
    if use == "ollama":
        try:
            log(f"  장면 선택: 로컬 LLM ({cfg.ollama_model})")
            return plan_ollama(sents, total, cfg, log, logos)
        except Exception as e:
            log(f"  로컬 LLM 실패({e}) → 키워드 규칙으로 대체")
    log("  장면 선택: 키워드 규칙")
    return plan_rules(sents, total, cfg, logos)
