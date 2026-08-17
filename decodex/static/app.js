"use strict";

/* decodex — browser client.
 *
 * The server owns the chess rules and all the facts; this file only draws them.
 * Legal moves come from /api/legal rather than being reimplemented here, so
 * there is one authority on legality and the UI cannot drift from it.
 */

const GLYPH = {
  P: "\u2659", N: "\u2658", B: "\u2657", R: "\u2656", Q: "\u2655", K: "\u2654",
  p: "\u265F", n: "\u265E", b: "\u265D", r: "\u265C", q: "\u265B", k: "\u265A",
};

const FILES = "abcdefgh";
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const DRAGON_FEN = "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15";

const $ = (id) => document.getElementById(id);

/* ---------------- helpers ---------------- */

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`Server returned ${res.status}`);
  }
  if (!res.ok) {
    const wait = data.retryAfterSeconds;
    throw new Error(data.error + (wait ? ` Try again in ${wait}s.` : ""));
  }
  return data;
}

function evalText(cp) {
  if (cp === null || cp === undefined) return "—";
  return (cp >= 0 ? "+" : "") + (cp / 100).toFixed(2);
}

function scoreText(cp, mate) {
  if (mate !== null && mate !== undefined) return `mate in ${Math.abs(mate)}`;
  return evalText(cp);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(title, extraClass) {
  const box = el("section", extraClass ? `card ${extraClass}` : "card");
  if (title) box.append(el("h3", null, title));
  return box;
}

function factList(items, extraClass) {
  const list = el("ul", extraClass ? `facts ${extraClass}` : "facts");
  items.forEach((item) => list.append(el("li", null, item)));
  return list;
}

function segmented(container, onChange) {
  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-side]");
    if (!button) return;
    [...container.querySelectorAll("button")].forEach((b) =>
      b.setAttribute("aria-pressed", String(b === button))
    );
    if (onChange) onChange(button.dataset.side);
  });
  return () =>
    container.querySelector('button[aria-pressed="true"]').dataset.side;
}

function fillRange(select, from, to, selected) {
  for (let value = from; value <= to; value += 1) {
    const option = el("option", null, String(value));
    option.value = String(value);
    if (value === selected) option.selected = true;
    select.append(option);
  }
}

/* ---------------- board ---------------- */

class Board {
  constructor(node, { onMove } = {}) {
    this.node = node;
    this.onMove = onMove;
    this.fen = START_FEN;
    this.legal = [];
    this.selected = null;
    this.lastMove = null;
    this.flipped = false;
    this.interactive = Boolean(onMove);
    node.addEventListener("click", (event) => this._onClick(event));
  }

  setPosition(fen, legal = []) {
    this.fen = fen;
    this.legal = legal;
    this.selected = null;
    this.render();
  }

  _onClick(event) {
    if (!this.interactive) return;
    const cell = event.target.closest("[data-square]");
    if (!cell) return;
    const square = cell.dataset.square;

    if (this.selected) {
      const move = this.legal.find(
        (m) => m.from === this.selected && m.to === square
      );
      if (move) {
        this.selected = null;
        // Promotion is offered as several moves to the same square; the UI
        // takes the queen, which is what a player means all but rarely.
        const chosen =
          this.legal.filter((m) => m.from === move.from && m.to === move.to)
            .find((m) => m.uci.endsWith("q")) || move;
        this.onMove(chosen);
        return;
      }
    }
    this.selected = this._hasOwnPiece(square) ? square : null;
    this.render();
  }

  _hasOwnPiece(square) {
    return this.legal.some((m) => m.from === square);
  }

  render() {
    const rows = this.fen.split(" ")[0].split("/");
    const grid = [];
    rows.forEach((row) => {
      const line = [];
      for (const ch of row) {
        if (/\d/.test(ch)) {
          for (let i = 0; i < Number(ch); i += 1) line.push(null);
        } else {
          line.push(ch);
        }
      }
      grid.push(line);
    });

    const targets = new Set(
      this.selected
        ? this.legal.filter((m) => m.from === this.selected).map((m) => m.to)
        : []
    );

    const rankOrder = this.flipped ? [...grid].reverse() : grid;
    this.node.replaceChildren();

    rankOrder.forEach((line, rowIndex) => {
      const rank = this.flipped ? rowIndex + 1 : 8 - rowIndex;
      const cells = this.flipped ? [...line].reverse() : line;
      cells.forEach((piece, colIndex) => {
        const file = this.flipped ? FILES[7 - colIndex] : FILES[colIndex];
        const square = `${file}${rank}`;
        const dark = (FILES.indexOf(file) + rank) % 2 === 0;
        const cell = el("button", `sq ${dark ? "dark" : "light"}`);
        cell.type = "button";
        cell.dataset.square = square;
        cell.setAttribute("aria-label", piece ? `${piece} on ${square}` : square);
        if (piece) {
          cell.classList.add(piece === piece.toUpperCase() ? "w" : "b");
          cell.append(el("span", "glyph", GLYPH[piece]));
        }
        if (square === this.selected) cell.classList.add("sel");
        if (targets.has(square)) cell.classList.add("target");
        if (this.lastMove && (square === this.lastMove.from || square === this.lastMove.to)) {
          cell.classList.add("last");
        }
        if (rank === 1) cell.append(el("span", "coord", file));
        this.node.append(cell);
      });
    });
  }
}

/* ---------------- position report ---------------- */

function renderPositionViews(target, views, depth) {
  target.replaceChildren();
  views.forEach((view) => target.append(...positionCards(view, depth)));
}

function positionCards(view, depth) {
  const cards = [];

  const hero = card(null, "hero");
  hero.append(el("p", "verdict", view.summary));
  const meta = el(
    "p",
    "note",
    `Explained for ${view.perspective} · depth ${depth} · evaluation ${evalText(view.evalCp)} from White's point of view`
  );
  hero.append(meta);
  if (view.freeTempoView) {
    hero.append(
      el(
        "p",
        "note",
        `It is ${view.turn}'s turn, so ${view.perspective}'s plans are shown as if handed the move.`
      )
    );
  }
  if (view.note) hero.append(el("p", "note", view.note));
  cards.push(hero);

  if (view.candidates.length) {
    const box = card(`Best moves for ${view.perspective}`);
    const lines = el("div", "lines");
    view.candidates.forEach((c) => {
      const line = el("div", c.rank === 1 ? "line top" : "line");
      line.append(el("span", "move", `${c.rank}. ${c.san}`));
      line.append(el("span", "score", scoreText(c.evalCp, c.mate)));
      line.append(el("span", "pv", c.line));
      lines.append(line);
    });
    box.append(lines);
    cards.push(box);
  }

  if (view.purposes.length) {
    const best = view.candidates[0] ? view.candidates[0].san : "The best move";
    const box = card(`${best} is good because it`);
    box.append(factList(view.purposes));
    cards.push(box);
  }

  const threats = [];
  if (view.threatBefore) threats.push(`Before: ${view.threatBefore.text}`);
  if (view.threatAfterBest) {
    const best = view.candidates[0] ? view.candidates[0].san : "the best move";
    threats.push(`After ${best}: ${view.threatAfterBest.text}`);
  }
  if (threats.length || view.neutralised.length || view.created.length) {
    const box = card("Threats");
    if (threats.length) box.append(factList(threats));
    if (view.neutralised.length) {
      box.append(el("h3", null, "This move defuses"));
      box.append(factList(view.neutralised, "defused"));
    }
    if (view.created.length) {
      box.append(el("h3", null, "This move concedes"));
      box.append(factList(view.created, "conceded"));
    }
    cards.push(box);
  }

  if (view.tactics.length) {
    const box = card("Tactics on the board");
    box.append(factList(view.tactics));
    cards.push(box);
  }

  if (view.hanging.length) {
    const box = card("Loose material");
    box.append(
      factList(
        view.hanging.map(
          (h) => `${h.piece} on ${h.square} falls to ${h.captureSan} (${evalText(h.lossCp)})`
        )
      )
    );
    cards.push(box);
  }

  if (view.observations.length) {
    const box = card("Pay attention to");
    box.append(factList(view.observations));
    cards.push(box);
  }

  if (view.roles.length) {
    const box = card(`Piece roles for ${view.perspective}`);
    box.append(factList(view.roles));
    cards.push(box);
  }

  if (view.concepts.length) {
    const box = card("Concepts");
    const kv = el("div", "kv");
    view.concepts.forEach((c) => {
      const row = el("div", "kv-row");
      row.append(el("span", "k", c.name));
      const value = el("span", "v", c.detail);
      if (c.favours) {
        value.append(el("span", `tag ${c.favours.toLowerCase()}`, c.favours));
      }
      row.append(value);
      kv.append(row);
    });
    box.append(kv);
    cards.push(box);
  }

  if (view.contributions.length) {
    const box = card(`Piece importance for ${view.perspective}`);
    const bars = el("div", "bars");
    const peak = Math.max(...view.contributions.map((c) => c.value), 1);
    view.contributions.forEach((c) => {
      const row = el("div", "bar-row");
      row.append(el("span", "name", `${c.piece} ${c.square}`));
      const track = el("div", "bar-track");
      const fill = el("div", "bar-fill");
      fill.style.width = `${(c.value / peak) * 100}%`;
      track.append(fill);
      row.append(track);
      const value = el("span", "val", c.value.toFixed(2));
      if (c.delta !== null && Math.abs(c.delta) >= 0.05) {
        value.append(
          el(
            "span",
            c.delta > 0 ? "delta" : "delta down",
            ` ${c.delta > 0 ? "+" : ""}${c.delta.toFixed(2)}`
          )
        );
      }
      row.append(value);
      bars.append(row);
    });
    box.append(bars);
    box.append(
      el("p", "note", "Stockfish's own NNUE evaluation change when each piece is removed, in pawns. The second figure is the change after the best move.")
    );
    cards.push(box);
  }

  return cards;
}

/* ---------------- game report ---------------- */

function renderGame(target, data) {
  target.replaceChildren();

  const head = card(null, "hero");
  const names = data.white || data.black
    ? `${data.white || "?"} vs ${data.black || "?"}`
    : "Game review";
  head.append(el("p", "verdict", names));
  head.append(
    el("p", "note", `Result ${data.result} · ${data.moves.length} half-moves · depth ${data.depth}`)
  );
  target.append(head);

  if (data.graph.length) {
    const box = card("Evaluation");
    const span = Math.min(
      500,
      Math.max(100, ...data.graph.map((cp) => Math.abs(cp)))
    );
    const graph = el("div", "graph");
    data.graph.forEach((cp, index) => {
      const cell = el("div", "stem-cell");
      const clipped = Math.max(-span, Math.min(span, cp));
      const stem = el("div", clipped >= 0 ? "stem plus" : "stem minus");
      stem.style.height = `${(Math.abs(clipped) / span) * 50}%`;
      stem.style.animationDelay = `${Math.min(index * 8, 600)}ms`;
      const move = data.moves[index];
      if (move) {
        cell.title = `${move.moveNumber}${move.mover === "White" ? "." : "..."} ${move.san} — ${evalText(cp)}`;
      }
      cell.append(stem);
      graph.append(cell);
    });
    box.append(graph);
    const legend = el("div", "graph-legend");
    legend.append(el("span", null, "White better above"));
    legend.append(el("span", null, `full height ${(span / 100).toFixed(2)}`));
    legend.append(el("span", null, "Black better below"));
    box.append(legend);
    target.append(box);
  }

  const sides = el("div", data.sides.length > 1 ? "sides two" : "sides");
  data.sides.forEach((side) => sides.append(sideCard(side)));
  target.append(sides);
}

function sideCard(side) {
  const box = card(side.side);

  const strip = el("div", "stat-strip");
  strip.append(stat(side.cleanPercent === null ? "—" : `${side.cleanPercent}%`, "clean moves"));
  strip.append(
    stat(side.averageLossCp === null ? "—" : (side.averageLossCp / 100).toFixed(2), "avg loss")
  );
  const total = Object.values(side.breakdown).reduce((a, b) => a + b, 0);
  strip.append(stat(String(total), "moves"));
  box.append(strip);

  const order = ["best", "excellent", "good", "inaccuracy", "mistake", "blunder", "forced"];
  const chips = el("div", "btn-row");
  order.forEach((key) => {
    if (!side.breakdown[key]) return;
    chips.append(el("span", `verdict-chip v-${key}`, `${side.breakdown[key]} ${key}`));
  });
  box.append(chips);

  if (side.turningPoints.length) {
    box.append(el("h3", null, "Turning points"));
    box.append(moveList(side.turningPoints));
  } else {
    box.append(el("p", "note", "No inaccuracies or worse."));
  }

  if (side.goodMoves.length) {
    box.append(el("h3", null, "Good moves"));
    box.append(moveList(side.goodMoves));
  }

  return box;
}

function stat(value, label) {
  const box = el("div", "stat");
  box.append(el("span", "n", value));
  box.append(el("span", "l", label));
  return box;
}

function moveList(moves) {
  const list = el("div", "moves");
  moves.forEach((move) => {
    const row = el("div", "move-row");
    row.append(el("span", "num", `${move.moveNumber}${move.mover === "White" ? "." : "..."}`));
    row.append(el("span", "san", move.san));
    row.append(el("span", `verdict-chip v-${move.verdict}`, move.verdict));
    row.append(el("span", "why", explainMove(move)));
    list.append(row);
  });
  return list;
}

function explainMove(move) {
  if (move.isError) {
    if (move.allowedMate) {
      return `${move.bestSan} was better and avoided mate in ${Math.abs(move.mateAfter)}.`;
    }
    let text = `Lost ${(move.lossCp / 100).toFixed(2)}; ${move.bestSan} was better.`;
    if (move.mateMissed !== null && move.mateMissed !== undefined) {
      text += ` Mate in ${move.mateMissed} was available.`;
    }
    return text;
  }
  if (move.swingCp > 0 && move.secondBestSan) {
    return `Clearly best — ${(move.swingCp / 100).toFixed(2)} better than ${move.secondBestSan}.`;
  }
  return `Evaluation ${evalText(move.evalCp)}.`;
}

/* ---------------- status ---------------- */

function busy(node, message) {
  node.className = "status-line";
  node.replaceChildren(el("span", "working", message));
}

function done(node, message = "") {
  node.className = "status-line";
  node.textContent = message;
}

function failed(node, error) {
  node.className = "status-line err";
  node.textContent = error.message || String(error);
}

/* ---------------- tabs ---------------- */

function wireTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((other) => {
        const active = other === tab;
        other.setAttribute("aria-selected", String(active));
        $(other.getAttribute("aria-controls")).hidden = !active;
      });
    });
  });
}

/* ---------------- position tab ---------------- */

function wirePosition(limits) {
  const board = new Board($("pos-board"));
  const sideOf = segmented($("pos-side"));
  const status = $("pos-status");
  const report = $("pos-report");

  fillRange($("pos-depth"), 8, limits.maxPositionDepth, Math.min(16, limits.maxPositionDepth));
  [...$("pos-multipv").options].forEach((option) => {
    if (Number(option.value) > limits.maxMultipv) option.remove();
  });

  async function refreshBoard() {
    const fen = $("pos-fen").value.trim();
    board.setPosition(fen.split(" ")[0] ? fen : START_FEN);
    const turn = fen.split(" ")[1] === "b" ? "Black" : "White";
    $("pos-turn").textContent = `${turn} to move`;
  }

  $("pos-fen").addEventListener("change", refreshBoard);
  $("pos-reset").addEventListener("click", () => {
    $("pos-fen").value = START_FEN;
    refreshBoard();
    $("pos-eval").textContent = "";
  });

  $("pos-go").addEventListener("click", async () => {
    const button = $("pos-go");
    button.disabled = true;
    busy(status, "Searching…");
    try {
      const data = await api("/api/position", {
        fen: $("pos-fen").value.trim(),
        side: sideOf(),
        depth: Number($("pos-depth").value),
        multipv: Number($("pos-multipv").value),
      });
      renderPositionViews(report, data.views, data.depth);
      $("pos-eval").textContent = evalText(data.views[0].evalCp);
      done(status, `Depth ${data.depth}`);
    } catch (error) {
      failed(status, error);
    } finally {
      button.disabled = false;
    }
  });

  $("pos-fen").value = DRAGON_FEN;
  refreshBoard();
}

/* ---------------- game tab ---------------- */

function wireGame(limits) {
  const sideOf = segmented($("game-side"));
  const status = $("game-status");
  const report = $("game-report");

  fillRange($("game-depth"), 6, limits.maxGameDepth, Math.min(10, limits.maxGameDepth));

  $("game-go").addEventListener("click", async () => {
    const button = $("game-go");
    const text = $("game-moves").value.trim();
    if (!text) {
      failed(status, new Error("Paste some moves first."));
      return;
    }
    button.disabled = true;
    busy(status, "Reviewing every move…");
    try {
      // A PGN has bracketed headers; a bare move list does not.
      const body = text.startsWith("[")
        ? { pgn: text, side: sideOf(), depth: Number($("game-depth").value) }
        : { moves: text, side: sideOf(), depth: Number($("game-depth").value) };
      const data = await api("/api/game", body);
      renderGame(report, data);
      done(status, `${data.moves.length} half-moves at depth ${data.depth}`);
    } catch (error) {
      failed(status, error);
    } finally {
      button.disabled = false;
    }
  });
}

/* ---------------- play tab ---------------- */

function wirePlay(limits) {
  const status = $("play-status");
  const report = $("play-report");
  const sideOf = segmented($("play-side"));
  let moves = [];
  let thinking = false;

  fillRange($("play-skill"), 0, 20, 5);

  const board = new Board($("play-board"), {
    onMove: async (move) => {
      if (thinking) return;
      moves.push(move.uci);
      board.lastMove = move;
      await sync();
      await botReply();
    },
  });

  async function sync() {
    const data = await api("/api/legal", { moves });
    board.setPosition(data.fen, data.over ? [] : data.legal);
    $("play-status-text").textContent = data.status;
    return data;
  }

  async function botReply() {
    const humanIsWhite = $("play-colour").value === "white";
    const state = await api("/api/legal", { moves });
    if (state.over) return;
    const botToMove = (state.turn === "white") !== humanIsWhite;
    if (!botToMove) return;

    thinking = true;
    busy(status, "Bot thinking…");
    try {
      const data = await api("/api/play", {
        moves,
        skill: Number($("play-skill").value),
        moveTime: 0.2,
      });
      if (data.move) {
        moves.push(data.move.uci);
        board.lastMove = {
          from: data.move.uci.slice(0, 2),
          to: data.move.uci.slice(2, 4),
        };
        $("play-last").textContent = `bot played ${data.move.san}`;
      }
      await sync();
      done(status, data.over ? data.status : "");
    } catch (error) {
      failed(status, error);
    } finally {
      thinking = false;
    }
  }

  async function newGame() {
    moves = [];
    board.lastMove = null;
    board.flipped = $("play-colour").value === "black";
    $("play-last").textContent = "";
    done(status, "");
    await sync();
    await botReply();
  }

  $("play-new").addEventListener("click", newGame);
  $("play-colour").addEventListener("change", newGame);

  $("play-undo").addEventListener("click", async () => {
    if (thinking) return;
    // Take back the pair, so it is the human's turn again.
    moves = moves.slice(0, Math.max(0, moves.length - 2));
    board.lastMove = null;
    await sync();
  });

  $("play-decode").addEventListener("click", async () => {
    const button = $("play-decode");
    button.disabled = true;
    busy(status, "Searching…");
    try {
      const state = await api("/api/legal", { moves });
      const data = await api("/api/position", {
        fen: state.fen,
        side: sideOf(),
        depth: Math.min(14, limits.maxPositionDepth),
      });
      renderPositionViews(report, data.views, data.depth);
      done(status, `Depth ${data.depth}`);
    } catch (error) {
      failed(status, error);
    } finally {
      button.disabled = false;
    }
  });

  $("play-review").addEventListener("click", async () => {
    const button = $("play-review");
    if (!moves.length) {
      failed(status, new Error("No moves played yet."));
      return;
    }
    button.disabled = true;
    busy(status, "Reviewing the game so far…");
    try {
      const data = await api("/api/game", {
        moves: moves.join(" "),
        side: sideOf(),
        depth: Math.min(8, limits.maxGameDepth),
      });
      renderGame(report, data);
      done(status, `${data.moves.length} half-moves at depth ${data.depth}`);
    } catch (error) {
      failed(status, error);
    } finally {
      button.disabled = false;
    }
  });

  newGame();
}

/* ---------------- boot ---------------- */

(async function start() {
  wireTabs();
  let limits = {
    maxPositionDepth: 18,
    maxGameDepth: 12,
    maxMultipv: 5,
    maxPlies: 160,
    engine: null,
  };
  try {
    const res = await fetch("/api/limits");
    if (res.ok) limits = await res.json();
  } catch {
    /* Defaults above match the server, so the UI still works. */
  }
  $("engine-name").textContent = limits.engine || "unavailable";
  $("limits-note").textContent = `depth ceiling ${limits.maxPositionDepth}`;

  wirePosition(limits);
  wireGame(limits);
  wirePlay(limits);
})();
