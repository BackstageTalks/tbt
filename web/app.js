const config = window.TBT_CONFIG || { apiBase: "" };

let selectedTour = "";

const el = (id) => document.getElementById(id);

const endpoint = (path) =>
  `${(config.apiBase || "").replace(/\/$/, "")}${path}`;

function fmtDate(value) {
  if (!value) return "TBA";

  const d = new Date(value);

  return new Intl.DateTimeFormat(
    undefined,
    {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "short",
    }
  ).format(d);
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

async function getJSON(path) {
  const response = await fetch(
    endpoint(path),
    {
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.error || `HTTP ${response.status}`
    );
  }

  return data;
}

function renderMatch(match) {
  const node = el(
    "matchTemplate"
  ).content.cloneNode(true);

  const card = node.querySelector(
    ".match-card"
  );

  card.querySelector(
    ".tour-pill"
  ).textContent =
    `${match.tour || "TOUR"} · ${
      (match.surface || "unknown")
        .replace("_", " ")
        .toUpperCase()
    }`;

  card.querySelector(
    ".tournament"
  ).textContent =
    match.tournament || "Tournament";

  card.querySelector(
    ".meta"
  ).textContent =
    `${fmtDate(match.scheduled_at)}${
      match.round
        ? ` · ${match.round}`
        : ""
    }`;

  const chip = card.querySelector(
    ".confidence-chip"
  );

  const band =
    match.prediction?.confidence_band
    || "low";

  chip.textContent =
    `${band} · ${
      pct(
        match.prediction
          ?.probability_pct
      )
    }`;

  chip.classList.add(band);

  [
    [
      ".player-one",
      match.player1,
    ],
    [
      ".player-two",
      match.player2,
    ],
  ].forEach(
    ([selector, player]) => {
      const box = card.querySelector(
        selector
      );

      box.querySelector(
        ".name"
      ).textContent =
        player?.name || "Unknown";

      box.querySelector(
        ".rank"
      ).textContent =
        player?.rank
          ? `#${player.rank}`
          : "NR";

      box.querySelector(
        ".pct"
      ).textContent =
        pct(
          player?.win_probability_pct
        );

      box.querySelector(
        ".prob"
      ).style.setProperty(
        "--p",
        `${
          Math.max(
            1,
            Math.min(
              99,
              player?.win_probability_pct
              || 50
            )
          )
        }%`
      );
    }
  );

  card.querySelector(
    ".pick"
  ).textContent =
    match.prediction?.winner_name
    || "—";

  const signals = card.querySelector(
    ".signals"
  );

  (
    match.prediction?.signals
    || []
  )
    .slice(0, 4)
    .forEach((signal) => {
      const tag =
        document.createElement("span");

      tag.className = "signal";

      tag.textContent =
        `${signal.factor} → ${
          signal.favours_player_name
        }`;

      signals.appendChild(tag);
    });

  if (!signals.children.length) {
    signals.textContent =
      "No strong secondary signal.";
  }

  card.querySelector(
    ".model-version"
  ).textContent =
    match.model_version
    || "model —";

  card.querySelector(
    ".generated"
  ).textContent =
    match.generated_at
      ? `generated ${
          fmtDate(match.generated_at)
        }`
      : "";

  return node;
}

async function load() {
  const status = el("status");

  status.classList.remove(
    "online"
  );

  status.querySelector(
    "span:last-child"
  ).textContent = "Updating";

  const query =
    new URLSearchParams({
      days: "3",
    });

  if (selectedTour) {
    query.set(
      "tour",
      selectedTour
    );
  }

  try {
    const [
      predictions,
      model,
    ] = await Promise.all([
      getJSON(
        `/api/v1/predictions/upcoming?${query}`
      ),
      getJSON(
        "/api/v1/model/status"
      ).catch(
        () => ({
          model: null,
        })
      ),
    ]);

    const board = el("board");

    board.innerHTML = "";

    (
      predictions.matches
      || []
    ).forEach(
      (match) =>
        board.appendChild(
          renderMatch(match)
        )
    );

    if (
      !predictions.matches?.length
    ) {
      board.innerHTML =
        '<div class="empty">No precomputed matches in the selected horizon yet.</div>';
    }

    const champion =
      model.champion
      || model.model
      || null;

    el(
      "metricMatches"
    ).textContent =
      predictions.count ?? 0;

    el(
      "metricModel"
    ).textContent =
      champion?.model_version
      || predictions.matches?.[0]
        ?.model_version
      || "—";

    el(
      "metricStatus"
    ).textContent =
      champion?.lifecycle_status
        ?.toUpperCase()
      || "—";

    const currentTime =
      new Date();

    el(
      "metricUpdated"
    ).textContent =
      currentTime.toLocaleTimeString(
        [],
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      );

    el(
      "updated"
    ).textContent =
      `Updated ${
        currentTime
          .toLocaleTimeString(
            [],
            {
              hour: "2-digit",
              minute: "2-digit",
            }
          )
      }`;

    status.classList.add(
      "online"
    );

    status.querySelector(
      "span:last-child"
    ).textContent =
      "BlinQ online";
  } catch (error) {
    el(
      "board"
    ).innerHTML =
      `<div class="empty">Could not load BlinQ: ${error.message}</div>`;

    status.querySelector(
      "span:last-child"
    ).textContent =
      "API unavailable";
  }
}

el(
  "refresh"
).addEventListener(
  "click",
  load
);

document
  .querySelectorAll(
    ".segment"
  )
  .forEach(
    (button) =>
      button.addEventListener(
        "click",
        () => {
          document
            .querySelectorAll(
              ".segment"
            )
            .forEach(
              (item) =>
                item.classList.remove(
                  "active"
                )
            );

          button.classList.add(
            "active"
          );

          selectedTour =
            button.dataset.tour
            || "";

          load();
        }
      )
  );

load();

setInterval(
  load,
  5 * 60 * 1000
);
