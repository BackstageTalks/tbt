# Blinq integration

The lowest-risk migration is to keep Blinq's UI and replace only its data source.

## Preferred endpoint

`GET /api/blinq/predictions?days=3`

Response:

```json
{
  "success": true,
  "source": "TBT-v200",
  "updated_at": "2026-09-01T10:00:00+00:00",
  "data": [
    {
      "id": "canonical-match-id",
      "date": "2026-09-01T14:00:00+00:00",
      "tour": "ATP",
      "tournament": "Example Open",
      "surface": "hard",
      "p1": "Player A",
      "p2": "Player B",
      "p1_prob": 64.2,
      "p2_prob": 35.8,
      "pick": "Player A",
      "probability": 64.2,
      "confidence": "medium",
      "model": "v200-...",
      "signals": []
    }
  ]
}
```

A richer contract is available at `GET /api/v1/predictions/upcoming`.

If the current Blinq code expects different field names, change only `api/tbt/services/contracts.py`; do not fork prediction logic to satisfy UI naming.
