"""
AI Singularity — 5차원 실험 컨텍스트 태그 자동 추출.

분석 요청의 experimental_context, project_name, timepoints에서
표준화된 5차원 태그를 자동 추출하여 학습 풀 격리에 사용한다.

5차원 태그:
  - ctx_sample_type:   in_vivo_tissue | in_vitro_cell | ex_vivo | organoid
  - ctx_cell_type:     muscle | neuron | hepatocyte | immune | epithelial | cardiac | other
  - ctx_environment:   microgravity | hypergravity | oxidative_stress | hypoxia |
                       nutrient_deprivation | radiation | normal
  - ctx_time_scale:    immediate | acute | subacute | chronic
  - ctx_disease_model: healthy | cancer | neurodegeneration | metabolic_syndrome |
                       muscle_atrophy | other

설계 원칙:
  - ctx_time_scale은 timepoints에서 직접 계산 (LLM 불필요)
  - 나머지 4차원은 LLM으로 추출하되, LLM 실패 시 키워드 기반 폴백 사용
  - 태그 추출 실패는 silently ignore (None 반환 → 학습 풀 매칭에서 제외)
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 표준 태그 값 정의
# ──────────────────────────────────────────────────────────────────────────────

VALID_SAMPLE_TYPES = {"in_vivo_tissue", "in_vitro_cell", "ex_vivo", "organoid"}
VALID_CELL_TYPES = {"muscle", "neuron", "hepatocyte", "immune", "epithelial", "cardiac", "other"}
VALID_ENVIRONMENTS = {
    "microgravity", "hypergravity", "oxidative_stress", "hypoxia",
    "nutrient_deprivation", "radiation", "normal",
}
VALID_TIME_SCALES = {"immediate", "acute", "subacute", "chronic"}
VALID_DISEASE_MODELS = {
    "healthy", "cancer", "neurodegeneration", "metabolic_syndrome",
    "muscle_atrophy", "other",
}

# ──────────────────────────────────────────────────────────────────────────────
# 시간 스케일 자동 분류
# ──────────────────────────────────────────────────────────────────────────────

_TIME_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(min|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks)",
    re.IGNORECASE,
)


def _parse_to_hours(timepoint: str) -> Optional[float]:
    """단일 timepoint 문자열을 시간(hours) 단위로 변환."""
    tp = str(timepoint).strip().lower()

    # "0" 또는 "0h" 등 기준점
    if tp in ("0", "0h", "0min", "0d", "baseline", "ctrl", "control"):
        return 0.0

    m = _TIME_PATTERN.search(tp)
    if not m:
        # 숫자만 있으면 시간(h)으로 간주
        try:
            return float(tp)
        except (ValueError, TypeError):
            return None

    value = float(m.group(1))
    unit = m.group(2).lower()

    if unit.startswith("min"):
        return value / 60.0
    elif unit.startswith(("h", "hr")):
        return value
    elif unit.startswith("d"):
        return value * 24.0
    elif unit.startswith("w"):
        return value * 168.0
    return None


def classify_time_scale(timepoints: List[str]) -> Optional[str]:
    """
    Timepoint 목록에서 생물학적 시간 스케일 자동 분류.

    반환:
      - 'immediate': max ≤ 1시간 (즉각 반응, 신호 전달 캐스케이드)
      - 'acute':     1시간 < max ≤ 24시간 (급성 반응, 전사 변화)
      - 'subacute':  24시간 < max ≤ 168시간/7일 (아급성, 단백질 발현 변화)
      - 'chronic':   max > 168시간/7일 (만성 적응, 구조적 변화)
    """
    hours_list = []
    for tp in timepoints:
        h = _parse_to_hours(tp)
        if h is not None:
            hours_list.append(h)

    if not hours_list:
        return None

    max_hours = max(hours_list)

    if max_hours <= 1.0:
        return "immediate"
    elif max_hours <= 24.0:
        return "acute"
    elif max_hours <= 168.0:
        return "subacute"
    else:
        return "chronic"


# ──────────────────────────────────────────────────────────────────────────────
# 키워드 기반 폴백 태그 추출
# ──────────────────────────────────────────────────────────────────────────────

_SAMPLE_TYPE_KEYWORDS = {
    "in_vivo_tissue": [
        "tissue", "in vivo", "animal", "mouse", "rat", "mice",
        "biopsy", "organ", "비복근", "gastrocnemius", "soleus",
    ],
    "in_vitro_cell": [
        "cell line", "in vitro", "culture", "c2c12", "hela", "hek293",
        "primary cell", "배양", "세포주",
    ],
    "ex_vivo": ["ex vivo", "explant", "slice"],
    "organoid": ["organoid", "spheroid", "3d culture"],
}

_CELL_TYPE_KEYWORDS = {
    "muscle": [
        "muscle", "myocyte", "myotube", "c2c12", "skeletal", "근육",
        "myoblast", "sarcomere", "gastrocnemius", "soleus",
    ],
    "neuron": ["neuron", "neural", "brain", "hippocampal", "cortical", "신경"],
    "hepatocyte": ["hepatocyte", "liver", "hepatic", "간"],
    "immune": ["immune", "macrophage", "t cell", "b cell", "lymphocyte", "면역"],
    "epithelial": ["epithelial", "keratinocyte", "상피"],
    "cardiac": ["cardiac", "cardiomyocyte", "heart", "심장"],
}

_ENVIRONMENT_KEYWORDS = {
    "microgravity": ["microgravity", "weightless", "무중력", "미세중력", "space", "iss"],
    "hypergravity": ["hypergravity", "centrifuge", "과중력"],
    "oxidative_stress": ["oxidative", "ros", "h2o2", "산화", "nac"],
    "hypoxia": ["hypoxia", "hypoxic", "저산소", "low oxygen"],
    "nutrient_deprivation": ["starvation", "serum free", "nutrient", "기아"],
    "radiation": ["radiation", "irradiation", "uv", "gamma", "방사선"],
}

_DISEASE_KEYWORDS = {
    "cancer": ["cancer", "tumor", "oncology", "carcinoma", "암"],
    "neurodegeneration": ["alzheimer", "parkinson", "neurodegeneration", "퇴행"],
    "metabolic_syndrome": ["diabetes", "obesity", "metabolic", "대사"],
    "muscle_atrophy": ["atrophy", "wasting", "sarcopenia", "위축"],
}


def _keyword_match(text: str, keyword_map: dict) -> Optional[str]:
    """텍스트에서 키워드 매칭으로 태그 추출."""
    text_lower = text.lower()
    for tag, keywords in keyword_map.items():
        for kw in keywords:
            if kw in text_lower:
                return tag
    return None


def _extract_tags_by_keywords(context_text: str) -> Dict[str, Optional[str]]:
    """키워드 기반 폴백 태그 추출."""
    return {
        "sample_type": _keyword_match(context_text, _SAMPLE_TYPE_KEYWORDS),
        "cell_type": _keyword_match(context_text, _CELL_TYPE_KEYWORDS),
        "environment": _keyword_match(context_text, _ENVIRONMENT_KEYWORDS),
        "disease_model": _keyword_match(context_text, _DISEASE_KEYWORDS),
    }


# ──────────────────────────────────────────────────────────────────────────────
# LLM 기반 태그 추출
# ──────────────────────────────────────────────────────────────────────────────

_LLM_EXTRACTION_PROMPT = """You are a bioinformatics expert. Extract standardized experiment context tags from the given information.

EXPERIMENT INFORMATION:
- Project Name: {project_name}
- Experimental Context: {context_json}

STANDARD TAG VALUES (choose ONLY from these):
- sample_type: in_vivo_tissue | in_vitro_cell | ex_vivo | organoid
- cell_type: muscle | neuron | hepatocyte | immune | epithelial | cardiac | other
- environment: microgravity | hypergravity | oxidative_stress | hypoxia | nutrient_deprivation | radiation | normal
- disease_model: healthy | cancer | neurodegeneration | metabolic_syndrome | muscle_atrophy | other

RULES:
- If uncertain, use "other" for cell_type or disease_model, "normal" for environment
- If no clear indication of disease, use "healthy"
- Return ONLY valid JSON with exactly these 4 keys

Return JSON:
"""


def _extract_tags_by_llm(
    experimental_context: dict,
    project_name: str,
    llm_client: Any,
) -> Optional[Dict[str, str]]:
    """LLM을 사용하여 4차원 태그 추출 (time_scale 제외)."""
    try:
        context_json = json.dumps(experimental_context, ensure_ascii=False, default=str)
        prompt = _LLM_EXTRACTION_PROMPT.format(
            project_name=project_name,
            context_json=context_json[:2000],  # 토큰 절약
        )

        response = llm_client.generate(
            system_prompt="You are a JSON-only responder. Return valid JSON only.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=200,
        )

        # JSON 파싱
        text = response.strip()
        # 코드 블록 제거
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        tags = json.loads(text)

        # 유효성 검증
        result = {}
        result["sample_type"] = tags.get("sample_type") if tags.get("sample_type") in VALID_SAMPLE_TYPES else None
        result["cell_type"] = tags.get("cell_type") if tags.get("cell_type") in VALID_CELL_TYPES else None
        result["environment"] = tags.get("environment") if tags.get("environment") in VALID_ENVIRONMENTS else None
        result["disease_model"] = tags.get("disease_model") if tags.get("disease_model") in VALID_DISEASE_MODELS else None

        return result

    except Exception as e:
        logger.debug(f"[ContextTagger] LLM extraction failed: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def extract_experiment_context(
    experimental_context: Optional[dict] = None,
    project_name: str = "",
    timepoints: Optional[List[str]] = None,
    llm_client: Any = None,
) -> Dict[str, Optional[str]]:
    """
    분석 요청에서 5차원 표준 태그를 추출한다.

    우선순위:
      1. ctx_time_scale: timepoints에서 직접 계산 (가장 정확)
      2. 나머지 4차원: LLM 추출 시도 → 실패 시 키워드 폴백

    반환:
      {
          'sample_type': 'in_vitro_cell' | None,
          'cell_type': 'muscle' | None,
          'environment': 'microgravity' | None,
          'time_scale': 'acute' | None,
          'disease_model': 'healthy' | None,
      }
    """
    result = {
        "sample_type": None,
        "cell_type": None,
        "environment": None,
        "time_scale": None,
        "disease_model": None,
    }

    # 1. time_scale: timepoints에서 직접 계산
    if timepoints:
        result["time_scale"] = classify_time_scale(timepoints)

    # 2. 나머지 4차원: LLM 시도
    llm_tags = None
    if llm_client and experimental_context:
        llm_tags = _extract_tags_by_llm(experimental_context, project_name, llm_client)

    if llm_tags:
        result["sample_type"] = llm_tags.get("sample_type")
        result["cell_type"] = llm_tags.get("cell_type")
        result["environment"] = llm_tags.get("environment")
        result["disease_model"] = llm_tags.get("disease_model")
    else:
        # 3. 키워드 폴백
        context_text = ""
        if project_name:
            context_text += project_name + " "
        if experimental_context:
            context_text += json.dumps(experimental_context, ensure_ascii=False, default=str)

        if context_text.strip():
            keyword_tags = _extract_tags_by_keywords(context_text)
            result["sample_type"] = keyword_tags.get("sample_type")
            result["cell_type"] = keyword_tags.get("cell_type")
            result["environment"] = keyword_tags.get("environment")
            result["disease_model"] = keyword_tags.get("disease_model")

    logger.info(f"[ContextTagger] Extracted tags: {result}")
    return result
