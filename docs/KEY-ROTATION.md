# Key-Rotation Checkliste

**Grund:** Alle Keys waren bis Commit `974a961` hardcoded im Code.
Die Git-History wurde mit `git-filter-repo` bereinigt und force-pushed.
Trotzdem muessen alle Keys rotiert werden, da GitHub alte Commits cached
und jeder fruehere Clone die Keys lokal hat.

## Status

| # | Key | Rotiert? | Anleitung |
|---|-----|----------|-----------|
| 1 | TELEGRAM_TOKEN | **JA — automatisch revoked via API** | Neuen Token bei @BotFather: `/revoke` dann `/token` oder `/newbot` |
| 2 | DIFY_API_KEY | OFFEN | Dify UI → Einstellungen → API Keys → Neuen erstellen, alten loeschen |
| 3 | DIFY_KB_ID | Kein Secret | Ist eine Dataset-ID, nicht rotierbar — aber pruefen ob korrekt |
| 4 | DIFY_KB_KEY | OFFEN | Dify UI → Knowledge → Dataset → API-Zugang → Key regenerieren |
| 5 | MEM0_API_KEY | OFFEN | https://app.mem0.ai → Settings → API Keys → Regenerate |
| 6 | MEM0_ORG_ID | Kein Secret | Org-ID, nicht rotierbar |
| 7 | MEM0_PROJECT_ID | Kein Secret | Project-ID, nicht rotierbar |

## Nach Rotation

1. Neue Werte in `/opt/cloud-code/.env` auf dem Server eintragen
2. Services neu starten:
   ```bash
   sudo systemctl restart cloud-code-orchestrator
   sudo systemctl restart cloud-code-telegram
   ```
3. Testen: Telegram-Bot anschreiben, pruefen ob Antwort kommt
4. `.env.example` im Repo ist bereits aktuell (keine Secrets drin)
