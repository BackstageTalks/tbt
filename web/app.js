const config =
  window.TBT_CONFIG || {
    apiBase: "",
  };

let selectedTour = "";

const el = (id) =>
  document.getElementById(id);

const endpoint = (path) =>
  `${
    (config.apiBase || "")
      .replace(/\/$/, "")
  }${path}`;

function safeText(value, fallback = "—") {
  const text =
    value === null ||
    value === undefined
      ? ""
      : String(value).trim();

  return text || fallback;
}

function probability(value) {
  const number =
    Number(value);

  if (!Number.isFinite(number)) {
    return 50;
  }

  return Math.max(
    0,
    Math.min(
      100,
      number
    )
  );
}

function pct(value) {
  return `${
    probability(value)
      .toFixed(1)
  }%`;
}

function formatMatchTime(value) {
  if (!value) {
    return "Time TBA";
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "Time TBA";
  }

  return new Intl
    .DateTimeFormat(
      undefined,
      {
        weekday: "short",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }
    )
    .format(date);
}

function formatGenerated(value) {
  if (!value) {
    return "";
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "";
  }

  return `Generated ${
    new Intl
      .DateTimeFormat(
        undefined,
        {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }
      )
      .format(date)
  }`;
}

function confidenceLabel(value) {
  const band =
    safeText(
      value,
      "low"
    )
      .toLowerCase();

  return {
    band,
    label:
      `${band} confidence`,
  };
}

function surfaceLabel(value) {
  return safeText(
    value,
    "unknown"
  )
    .replaceAll(
      "_",
      " "
    )
    .toUpperCase();
}

async function getJSON(path) {
  const response =
    await fetch(
      endpoint(path),
      {
        headers: {
          Accept:
            "application/json",
        },

        cache:
          "no-store",
      }
    );

  let data;

  try {
    data =
      await response.json();
  } catch {
    throw new Error(
      `Invalid API response (${response.status})`
    );
  }

  if (!response.ok) {
    throw new Error(
      data?.error ||
      `HTTP ${response.status}`
    );
  }

  return data;
}

function setStatus(
  text,
  state = ""
) {
  const status =
    el("status");

  status.classList.remove(
    "online",
    "error"
  );

  if (state) {
    status.classList.add(
      state
    );
  }

  status
    .querySelector(
      ".status-text"
    )
    .textContent =
      text;
}

function renderSignal(
  container,
  signal
) {
  if (
    !signal ||
    typeof signal !==
      "object"
  ) {
    return;
  }

  const factor =
    safeText(
      signal.factor,
      ""
    );

  const player =
    safeText(
      signal.favours_player_name,
      ""
    );

  if (
    !factor &&
    !player
  ) {
    return;
  }

  const tag =
    document
      .createElement(
        "span"
      );

  tag.className =
    "signal";

  if (
    factor &&
    player
  ) {
    tag.textContent =
      `${factor} · ${player}`;
  } else {
    tag.textContent =
      factor || player;
  }

  container.appendChild(
    tag
  );
}

function renderPlayer(
  card,
  selector,
  player
) {
  const box =
    card
      .querySelector(
        selector
      );

  const name =
    safeText(
      player?.name,
      "Unknown player"
    );

  const rank =
    player?.rank
      ? `#${player.rank}`
      : "NR";

  const chance =
    probability(
      player
        ?.win_probability_pct
    );

  box
    .querySelector(
      ".name"
    )
    .textContent =
      name;

  box
    .querySelector(
      ".rank"
    )
    .textContent =
      rank;

  box
    .querySelector(
      ".pct"
    )
    .textContent =
      pct(chance);

  box
    .querySelector(
      ".prob-fill"
    )
    .style
    .setProperty(
      "--probability",
      `${chance}%`
    );
}

function renderMatch(match) {
  const node =
    el(
      "matchTemplate"
    )
      .content
      .cloneNode(true);

  const card =
    node
      .querySelector(
        ".match-card"
      );

  const tour =
    safeText(
      match?.tour,
      "TOUR"
    )
      .toUpperCase();

  const confidence =
    confidenceLabel(
      match
        ?.prediction
        ?.confidence_band
    );

  const predictionProbability =
    probability(
      match
        ?.prediction
        ?.probability_pct
    );

  card
    .querySelector(
      ".tour-pill"
    )
    .textContent =
      tour;

  card
    .querySelector(
      ".surface-pill"
    )
    .textContent =
      surfaceLabel(
        match?.surface
      );

  card
    .querySelector(
      ".tournament"
    )
    .textContent =
      safeText(
        match?.tournament,
        "Tournament"
      );

  card
    .querySelector(
      ".match-time"
    )
    .textContent =
      formatMatchTime(
        match
          ?.scheduled_at
      );

  const round =
    card
      .querySelector(
        ".round"
      );

  const roundText =
    safeText(
      match?.round,
      ""
    );

  if (roundText) {
    round.textContent =
      roundText;
  } else {
    round.remove();
  }

  const chip =
    card
      .querySelector(
        ".confidence-chip"
      );

  chip.textContent =
    confidence.label;

  chip.classList.add(
    confidence.band
  );

  card
    .querySelector(
      ".pick"
    )
    .textContent =
      safeText(
        match
          ?.prediction
          ?.winner_name,
        "No pick"
      );

  card
    .querySelector(
      ".pick-probability"
    )
    .textContent =
      pct(
        predictionProbability
      );

  renderPlayer(
    card,
    ".player-one",
    match?.player1
  );

  renderPlayer(
    card,
    ".player-two",
    match?.player2
  );

  const signals =
    card
      .querySelector(
        ".signals"
      );

  const sourceSignals =
    Array.isArray(
      match
        ?.prediction
        ?.signals
    )
      ? match
          .prediction
          .signals
      : [];

  sourceSignals
    .slice(
      0,
      4
    )
    .forEach(
      (signal) =>
        renderSignal(
          signals,
          signal
        )
    );

  if (
    !signals.children.length
  ) {
    signals.textContent =
      "No strong secondary signal.";
  }

  card
    .querySelector(
      ".model-version"
    )
    .textContent =
      safeText(
        match?.model_version,
        "Model —"
      );

  card
    .querySelector(
      ".generated"
    )
    .textContent =
      formatGenerated(
        match?.generated_at
      );

  return node;
}

function showEmpty(message) {
  const board =
    el("board");

  board.innerHTML = "";

  const empty =
    document
      .createElement(
        "div"
      );

  empty.className =
    "empty-state";

  empty.textContent =
    message;

  board.appendChild(
    empty
  );
}

function updateOverview(
  predictions,
  model
) {
  const champion =
    model?.champion ||
    model?.model ||
    null;

  el(
    "metricMatches"
  )
    .textContent =
      predictions
        ?.count ??
      predictions
        ?.matches
        ?.length ??
      0;

  el(
    "metricModel"
  )
    .textContent =
      champion
        ?.model_version ||
      predictions
        ?.matches
        ?.[0]
        ?.model_version ||
      "—";

  el(
    "metricStatus"
  )
    .textContent =
      safeText(
        champion
          ?.lifecycle_status,
        "—"
      )
        .toUpperCase();

  const now =
    new Date();

  const time =
    now
      .toLocaleTimeString(
        [],
        {
          hour:
            "2-digit",
          minute:
            "2-digit",
        }
      );

  el(
    "metricUpdated"
  )
    .textContent =
      time;

  el(
    "updated"
  )
    .textContent =
      `Updated ${time}`;
}

async function load() {
  const refresh =
    el("refresh");

  refresh.disabled =
    true;

  refresh.textContent =
    "Updating…";

  setStatus(
    "Updating"
  );

  const query =
    new URLSearchParams(
      {
        days: "3",
      }
    );

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
    ] =
      await Promise.all([
        getJSON(
          `/api/v1/predictions/upcoming?${query}`
        ),

        getJSON(
          "/api/v1/model/status"
        )
          .catch(
            () => ({
              champion:
                null,
              model:
                null,
            })
          ),
      ]);

    const matches =
      Array.isArray(
        predictions
          ?.matches
      )
        ? predictions
            .matches
        : [];

    const board =
      el("board");

    board.innerHTML =
      "";

    if (
      !matches.length
    ) {
      showEmpty(
        "No upcoming BlinQ predictions in the selected horizon."
      );
    } else {
      matches
        .forEach(
          (match) => {
            board
              .appendChild(
                renderMatch(
                  match
                )
              );
          }
        );
    }

    updateOverview(
      predictions,
      model
    );

    setStatus(
      "BlinQ online",
      "online"
    );
  } catch (error) {
    showEmpty(
      `Could not load predictions: ${
        error?.message ||
        "unknown error"
      }`
    );

    setStatus(
      "API unavailable",
      "error"
    );
  } finally {
    refresh.disabled =
      false;

    refresh.textContent =
      "Refresh board";
  }
}

el("refresh")
  .addEventListener(
    "click",
    load
  );

document
  .querySelectorAll(
    ".segment"
  )
  .forEach(
    (button) => {
      button
        .addEventListener(
          "click",
          () => {
            document
              .querySelectorAll(
                ".segment"
              )
              .forEach(
                (item) =>
                  item
                    .classList
                    .remove(
                      "active"
                    )
              );

            button
              .classList
              .add(
                "active"
              );

            selectedTour =
              button
                .dataset
                .tour ||
              "";

            load();
          }
        );
    }
  );

load();

setInterval(
  load,
  5 * 60 * 1000
);
