# [2026-05-26] Ollama 모델 경로 — `OLLAMA_MODELS`가 재부팅 후에도 C로 잡힘

## 증상

- 모델 저장 위치를 **`D:\ollama\models`** 로 옮기고, Windows **시스템(또는 사용자) 환경 변수** `OLLAMA_MODELS=D:\ollama\models` 설정
- `ollama pull hermes3:8b` 성공, `ollama list`에 3모델 표시
- **PC 재부팅** 후에도 `%LOCALAPPDATA%\Ollama\server.log` 첫 줄:

  `OLLAMA_MODELS:C:\Users\tmdgu\.ollama\models`

- 추론 로그(`server-3.log` 등)에서 blob 경로도 **C:\Users\tmdgu\.ollama\models\blobs\...** 로 계속 기록

## 기대 vs 실제

| 항목 | 기대 | 실제 |
|------|------|------|
| 환경 변수 | 재부팅·Quit 후 D 경로 반영 | 로그에는 **C 고정** |
| 디스크 | Hermes 등 신규 pull이 D에 쌓임 | C·D **둘 다** `blobs` 14개 (복사본 존재) |
| PowerShell | `$env:OLLAMA_MODELS` 또는 레지스트리 확인 시 D | **HKLM**에 D 있음, **HKCU(사용자)** 에는 변수 없을 수 있음 |

## 환경

- Windows 10/11, Ollama **0.24.0** (트레이 앱 + `ollama.exe`)
- RTX 3080 10GB, 모델: `qwen3:8b`, `nomic-embed-text`, `hermes3:8b` (Phase 4 PoC용)
- MALA: Phase 3 RAG 완료 직후, Hermes 라우터 PoC 준비 단계

## 시도한 것

| # | 시도 | 결과 |
|---|------|------|
| 1 | 사용자 환경 변수 `OLLAMA_MODELS=D:\ollama\models` | ❌ `server.log` 여전히 C |
| 2 | `C:\Users\tmdgu\.ollama\models` → `D:\ollama\models` 복사/이동 | ⚠️ C·D 양쪽에 동일 blob 수 — Ollama는 C 계속 사용 |
| 3 | Ollama 트레이 **Quit** 후 재실행 | ❌ 로그 타임스탬프만 갱신, 경로는 C |
| 4 | **PC 재부팅** | ❌ 동일 (22:03:33 로그 기준) |
| 5 | **시스템(Machine) 변수** `OLLAMA_MODELS` (HKLM) | ❌ 단독으로는 트레이 앱에 미반영 |
| 6 | `db.sqlite` `settings.models` → `D:\ollama\models` | ✅ DB 값 변경 (아래 해결) |
| 7 | (권장) C `models` 폴더 **junction** → D | ⏳ 트레이 재시작 후 로그로 최종 확인 |

## 원인 (확정)

**Ollama 0.24 Windows 데스크톱 앱**은 첫 실행 시 모델 경로를 SQLite에 저장하고, 이후 **`OLLAMA_MODELS` 환경 변수보다 DB 값을 우선**하는 동작이 관측됨.

```
%LOCALAPPDATA%\Ollama\db.sqlite
  └── settings.models  →  'C:\Users\tmdgu\.ollama\models'  (고정)
```

- 재부팅은 정상이었으나, **앱 내부 설정이 C로 남아** 서버가 C를 읽음.
- C에 기존 `models` 폴더·blob이 남아 있으면, env만 바꿔도 **C를 계속 쓰는** 사례가 커뮤니티에 보고됨 ([ollama#9889](https://github.com/ollama/ollama/issues/9889)).

## 해결 / 우회 (확정 — 2026-05-26)

- `db.sqlite` → `D:\ollama\models` · `server.log`에 `OLLAMA_MODELS:D:\ollama\models` 확인
- C `C:\Users\tmdgu\.ollama\models` → `models_old` 후 삭제 · `ollama list` 3모델 유지

### A. DB 수정 (적용함)

1. Ollama **완전 종료** (트레이 Quit, 필요 시 `taskkill /IM ollama.exe /F`)
2. `db.sqlite`의 `settings` 테이블 `models` 컬럼을 `D:\ollama\models`로 변경
3. **시작 메뉴**에서 Ollama 다시 실행 (PowerShell에서 `ollama serve`만 띄우지 말 것)
4. `explorer %LOCALAPPDATA%\Ollama` → `server.log` **맨 위**에 `OLLAMA_MODELS` 또는 blob 경로가 **D**인지 확인

PowerShell에서 DB 확인 예:

```powershell
# 경로만 확인 (Python 등)
python -c "import sqlite3; c=sqlite3.connect(r'$env:LOCALAPPDATA\Ollama\db.sqlite'); print(c.execute('SELECT models FROM settings').fetchone())"
```

### B. Junction (DB만으로 안 될 때, 관리자 CMD)

```cmd
taskkill /IM ollama.exe /F
ren "C:\Users\tmdgu\.ollama\models" models_old
mklink /J "C:\Users\tmdgu\.ollama\models" "D:\ollama\models"
```

C 경로는 유지되지만 실제 파일 I/O는 D로 향함 — 로그가 C를 찍어도 **디스크 사용량은 D**만 늘어남.

### C. 환경 변수 정리 (권장)

- **사용자 + 시스템** 둘 다 `OLLAMA_MODELS=D:\ollama\models` (값 동일)
- PowerShell: `%OLLAMA_MODELS%` 대신 `$env:OLLAMA_MODELS` 또는  
  `[Environment]::GetEnvironmentVariable('OLLAMA_MODELS','Machine')`

## 교훈 (한 줄)

> **Windows Ollama 0.24에서는 “재부팅 + env”만으로 부족할 수 있음** — `db.sqlite`의 `settings.models`와 C 쪽 잔여 `models` 폴더를 함께 본다.

## MALA 연계

- Phase 4 PoC(`hermes3:8b`, `USE_HERMES_ROUTER`) 전에 **디스크·경로를 D로 고정**해야 C 드라이브 부족·이중 blob 혼선을 피할 수 있음.
- `.env`에 `OLLAMA_ROUTER_MODEL=hermes3:8b` 등 추가 후 `run_hermes_once.py` / `measure_router_vram.py` 실행.

## 참고

- Ollama Windows 문서: [Changing Model Location](https://docs.ollama.com/windows)
- 로그 위치: `%LOCALAPPDATA%\Ollama\server.log`, `app.log`
- [`../docs/development-log.md`](../docs/development-log.md) — 2026-05-26 절
- [`../docs/decisions/003-phase4-hermes-router.md`](../docs/decisions/003-phase4-hermes-router.md)
