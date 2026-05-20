# Troubleshooting

MALA 개발 중 막힌 이슈를 **증상 → 가설 → 시도 → 결과 → 교훈** 형식으로 남깁니다.  
“완벽한 시스템”보다 **이 기록이 설계·구현 신뢰도를 만듭니다.**

---

## 인덱스

| 날짜 | 제목 | 상태 |
|------|------|------|
| 2026-05-20 | [MoE 35B가 RTX 3080 10GB에 올라가지 않음](2026-05-20-moe-vram.md) | ✅ 원인 확정 (문서) |
| _TBD_ | docker-compose GPU / YAML 오류 | ⏳ |
| _TBD_ | vLLM vs Ollama 포맷 불일치 | ⏳ |
| _TBD_ | Redis Envelope 파싱 실패 | ⏳ |

---

## 새 이슈 작성 템플릿

파일명: `YYYY-MM-DD-짧은-제목.md`

```markdown
# [날짜] 제목

## 증상
## 기대 vs 실제
## 환경
- GPU / 드라이버 / OS / 도구 버전

## 시도한 것
| # | 시도 | 결과 |
|---|------|------|
| 1 | | |

## 원인 (확정 또는 추정)
## 해결 / 우회
## 교훈 (한 줄)
## 참고
- 명령어, 로그, 링크
```

---

## 관련 문서

- [`../docs/model-comparison.md`](../docs/model-comparison.md)
- [`../docs/decisions/`](../docs/decisions/)
