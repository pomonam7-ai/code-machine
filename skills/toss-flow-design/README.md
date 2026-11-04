# Toss Flow Design

토스 실앱에서 관찰한 UX 패턴을 업종에 맞는 모바일 앱과 반응형 웹 흐름으로 바꾸는 Codex 스킬입니다.

## 다루는 내용

- 요약 정보와 다음 행동을 같은 맥락에 배치
- 최근 작업·진행 중인 작업에서 이어가기
- 핵심 질문에 집중하는 입력 화면과 선택 정보의 점진적 노출
- 실행·접수·처리 중·완료 상태 구분
- 업무형·예약형·쇼핑형·학습형 서비스에 맞는 탐색 구조

프레임워크나 API 키, Mobile MCP 없이 사용할 수 있습니다. 실제 앱 조사는 필요한 경우 별도로 수행합니다. 토스의 공식 제품이나 공식 디자인 시스템이 아니며, 원본 로고·스크린샷·개인 금융 정보를 포함하지 않습니다.

## 설치

이 폴더(`skills/toss-flow-design`)를 `toss-flow-design`이라는 이름으로 개인 Codex 스킬 디렉터리에 복사합니다.

```text
~/.codex/skills/toss-flow-design/
  SKILL.md
  agents/openai.yaml
  references/
    observations.md
    domain-mapping.md
```

Codex의 스킬 설치 기능에 저장소 주소와 `skills/toss-flow-design` 경로를 함께 전달해 설치할 수도 있습니다. 새로 설치한 스킬이 표시되지 않으면 새 세션에서 확인하세요.

## 사용 예시

```text
$toss-flow-design 예약 서비스의 사용자 동선과 모바일 화면을 만들어줘.
```

```text
$toss-flow-design 기존 CRM의 고객 선택부터 상담 기록까지 동선을 개선해줘.
```

```text
$toss-flow-design 교육 앱에서 처음 탐색하는 사용자와 이어서 학습하는 사용자의 흐름을 설계해줘.
```

## 파일

- [SKILL.md](SKILL.md): 적용 범위, 설계 과정, 구현과 검증 지침
- [관찰 근거](references/observations.md): 실제로 관찰한 화면과 미확인 범위
- [분야별 적용](references/domain-mapping.md): 업종별 대상·행동·상태 치환 예시

## 분석 범위

2026년 11월 4일 갤럭시 S25의 토스 앱에서 홈·전체·검색·송금 진입·설정·혜택·쇼핑의 주요 화면을 확인했습니다. 전체 기능의 전수 분석은 아닙니다. 송금 완료, 상품 신청, 결제 및 증권 내부 흐름은 검증하지 않았습니다. 일반 설계 권고와 실제 관찰 사실을 구분해 기록했습니다.
