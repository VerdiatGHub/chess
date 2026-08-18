"use strict";

/* decodex — browser client.
 *
 * The server owns the chess rules and all the facts; this file only draws them.
 * Legal moves come from /api/legal rather than being reimplemented here, so
 * there is one authority on legality and the UI cannot drift from it.
 */

// Piece art is lichess's cburnett set, served from /assets/pieces.
const PIECE_FILE = {
  P: "wP", N: "wN", B: "wB", R: "wR", Q: "wQ", K: "wK",
  p: "bP", n: "bN", b: "bB", r: "bR", q: "bQ", k: "bK",
};

// Spoken labels, so the board is navigable without sight of it.
const PIECE_NAME = {
  P: "white pawn", N: "white knight", B: "white bishop",
  R: "white rook", Q: "white queen", K: "white king",
  p: "black pawn", n: "black knight", b: "black bishop",
  r: "black rook", q: "black queen", k: "black king",
};

// FILES, isLightSquare and expandFen come from board.js, which is loaded first.
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

/* A list of facts. Items are `{text, cue}` from the server, or bare strings for
 * lines the UI composes itself; `bind` attaches the geometry where there is any.
 */
function factList(items, extraClass, bind = noBind, fen) {
  const list = el("ul", extraClass ? `facts ${extraClass}` : "facts");
  items.forEach((item) => {
    const text = typeof item === "string" ? item : item.text;
    const node = el("li", null, text);
    if (typeof item !== "string") bind(node, item.cue, fen);
    list.append(node);
  });
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

// Arrowheads are drawn as polygons rather than SVG markers, because a marker
// scales with stroke width. Units are board squares (overlay viewBox is 8x8).
const ARROW_HEAD = 0.28;
const ARROW_HALF_WIDTH = 0.11;

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, className) {
  const node = document.createElementNS(SVG_NS, tag);
  if (className) node.setAttribute("class", className);
  return node;
}

/* One arrow as a line plus a head, in the overlay's 8x8 coordinate space. */
function arrowShapes(from, to, flipped, tone) {
  const line = arrowGeometry(from, to, flipped);
  if (!line) return [];
  const dx = line.x2 - line.x1;
  const dy = line.y2 - line.y1;
  const span = Math.sqrt(dx * dx + dy * dy);
  if (span === 0) return [];
  const ux = dx / span;
  const uy = dy / span;

  // The shaft stops where the head begins, so the two do not overlap.
  const shaft = svg("line", `arrow ${tone}`);
  shaft.setAttribute("x1", line.x1);
  shaft.setAttribute("y1", line.y1);
  shaft.setAttribute("x2", line.x2 - ux * ARROW_HEAD);
  shaft.setAttribute("y2", line.y2 - uy * ARROW_HEAD);

  const baseX = line.x2 - ux * ARROW_HEAD;
  const baseY = line.y2 - uy * ARROW_HEAD;
  const head = svg("polygon", `arrow-head ${tone}`);
  head.setAttribute(
    "points",
    [
      `${line.x2},${line.y2}`,
      `${baseX - uy * ARROW_HALF_WIDTH},${baseY + ux * ARROW_HALF_WIDTH}`,
      `${baseX + uy * ARROW_HALF_WIDTH},${baseY - ux * ARROW_HALF_WIDTH}`,
    ].join(" ")
  );
  return [shaft, head];
}

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
    // Geometry for the fact currently being hovered, and the position it was
    // measured on, which for a game review is not the position on the board.
    this.cue = null;
    this.previewFen = null;
    this.overlay = svg("svg", "overlay");
    this.overlay.setAttribute("viewBox", "0 0 8 8");
    this.overlay.setAttribute("preserveAspectRatio", "none");
    this.overlay.setAttribute("aria-hidden", "true");
    node.addEventListener("click", (event) => this._onClick(event));
  }

  setPosition(fen, legal = []) {
    this.fen = fen;
    this.legal = legal;
    this.selected = null;
    // A new position invalidates any geometry drawn for the old one.
    this.cue = null;
    this.previewFen = null;
    this.render();
  }

  /* Draw one fact's geometry, optionally on the position it was measured on. */
  showCue(cue, fen) {
    this.cue = cue || null;
    this.previewFen = fen || null;
    this.render();
  }

  clearCue() {
    this.cue = null;
    this.previewFen = null;
    this.render();
  }

  _onClick(event) {
    if (!this.interactive) return;
    // While a past position is on show, the legal moves belong to the live one,
    // so a click here would mean something other than what the player sees.
    if (this.previewFen) return;
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
    // While a cue is showing a different position, that position is what the
    // arrows were measured against, so it is what must be drawn.
    const fen = this.previewFen || this.fen;
    const grid = expandFen(fen);
    // A malformed FEN draws nothing rather than a ragged grid.
    if (!grid) {
      this.node.replaceChildren();
      return;
    }

    const targets = new Set(
      this.selected
        ? this.legal.filter((m) => m.from === this.selected).map((m) => m.to)
        : []
    );
    const marks = new Map(
      (this.cue ? this.cue.marks : []).map((mark) => [mark.square, mark.tone])
    );

    this.node.replaceChildren();
    for (const cell of boardOrder(this.flipped)) {
      // `grid` is indexed from rank 8 down, which is how a FEN is written.
      const piece = grid[8 - cell.rank][cell.fileIndex];
      const node = el("button", `sq ${cell.light ? "light" : "dark"}`);
      node.type = "button";
      node.dataset.square = cell.square;
      node.setAttribute(
        "aria-label",
        piece ? `${PIECE_NAME[piece]} on ${cell.square}` : cell.square
      );

      if (piece) {
        const img = el("img", "piece");
        img.src = `/assets/pieces/${PIECE_FILE[piece]}.svg`;
        img.alt = "";
        img.draggable = false;
        node.append(img);
      }
      if (cell.square === this.selected) node.classList.add("sel");
      if (targets.has(cell.square)) {
        node.classList.add(piece ? "capture" : "target");
      }
      if (this.lastMove && !this.cue &&
          (cell.square === this.lastMove.from || cell.square === this.lastMove.to)) {
        node.classList.add("last");
      }
      if (marks.has(cell.square)) {
        node.classList.add(`mark-${marks.get(cell.square)}`);
      }
      if (cell.showFile) {
        node.append(el("span", "coord file", FILES[cell.fileIndex]));
      }
      if (cell.showRank) {
        node.append(el("span", "coord rank", String(cell.rank)));
      }
      this.node.append(node);
    }

    this.overlay.replaceChildren();
    for (const item of this.cue ? this.cue.arrows : []) {
      this.overlay.append(...arrowShapes(item.from, item.to, this.flipped, item.tone));
    }
    this.node.append(this.overlay);
  }
}

/* Bind report items to a board, so hovering a statement draws it.
 *
 * A fresh binder per rendered report, because the pin it remembers belongs to
 * nodes that the next render throws away. Click pins the cue, which is the only
 * way to see it on a touch screen.
 *
 * `onLabel` is called with the label of the item being shown, or null when
 * nothing is, so a caller can caption the board.
 */
function cueBinder(board, onLabel) {
  let pinned = null;
  const label = (text) => {
    if (onLabel) onLabel(text);
  };
  return function bind(node, cue, fen, text) {
    if (!cue || (!cue.marks.length && !cue.arrows.length)) return node;
    node.classList.add("cued");
    // Focusable, so the geometry is reachable without a pointer. The nodes are
    // list items and divs, so they need the tab stop declared.
    node.tabIndex = 0;
    const show = () => {
      board.showCue(cue, fen);
      label(text || null);
    };
    const hide = () => {
      if (pinned === node) return;
      board.clearCue();
      label(null);
    };
    const toggle = () => {
      if (pinned === node) {
        pinned = null;
        node.classList.remove("pinned");
        node.setAttribute("aria-pressed", "false");
        board.clearCue();
        label(null);
        return;
      }
      if (pinned) {
        pinned.classList.remove("pinned");
        pinned.setAttribute("aria-pressed", "false");
      }
      pinned = node;
      node.classList.add("pinned");
      node.setAttribute("aria-pressed", "true");
      show();
    };
    node.setAttribute("role", "button");
    node.setAttribute("aria-pressed", "false");
    node.addEventListener("mouseenter", show);
    node.addEventListener("mouseleave", hide);
    node.addEventListener("focusin", show);
    node.addEventListener("focusout", hide);
    node.addEventListener("click", toggle);
    node.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle();
    });
    return node;
  };
}

/* A binder that does nothing, for reports rendered without a board. */
const noBind = (node) => node;

/* ---------------- position report ---------------- */

function renderPositionViews(target, views, depth, bind = noBind, onSelectPly) {
  target.replaceChildren();
  const fragment = document.createDocumentFragment();

  views.forEach((view) => {
    const cards = positionCards(view, depth, bind, onSelectPly);
    const tabGroup = createReportTabs(cards);
    fragment.appendChild(tabGroup);
  });

  target.appendChild(fragment);
}

function createReportTabs(cards) {
  // Categorize cards into tabs based on their content
  const tabs = {
    "Summary": [],
    "Piece Roles": [],
    "Threats": [],
    "Tactics": [],
    "Plans": [],
    "Concepts": [],
    "Other": []
  };

  cards.forEach((card) => {
    const titleEl = card.querySelector("h3");
    let category = "Other";

    if (!titleEl) {
      // No title = summary/hero card
      category = "Summary";
    } else {
      const title = titleEl.textContent || "";
      if (title.includes("Explaining the best line") || title.includes("Other lines")) {
        category = "Summary";
      } else if (title.includes("Best moves")) {
        category = "Plans";
      } else if (title.includes("is good because") || title.includes("is beneficial")) {
        category = "Plans";
      } else if (title.includes("Threats") || title.includes("defuses") || title.includes("concedes") ||
                 title.includes("Before:") || title.includes("After")) {
        category = "Threats";
      } else if (title.includes("Tactics")) {
        category = "Tactics";
      } else if (title.includes("Loose material")) {
        category = "Threats";
      } else if (title.includes("Pay attention")) {
        category = "Other";
      } else if (title.includes("Piece roles") || title.includes("role")) {
        category = "Piece Roles";
      } else if (title.includes("Concepts") || title.includes("Space") || title.includes("Material") ||
                 title.includes("King safety") || title.includes("Pawn") || title.includes("Development")) {
        category = "Concepts";
      } else if (title.includes("Piece importance")) {
        category = "Other";
      }
    }

    tabs[category].push(card);
  });

  // Build tab container
  const tabContainer = el("div", "report-tabs");
  const tabNav = el("div", "tab-nav");
  const tabWrapper = el("div", "tab-panel-wrapper");

  // Create tabs for categories that have content
  let first = true;
  let hasMultipleTabs = 0;

  Object.entries(tabs).forEach(([tabName, tabCards]) => {
    if (tabCards.length === 0) return;
    hasMultipleTabs++;

    const button = el("button", "tab-button", tabName);
    button.dataset.tab = tabName;
    button.id = `tab-${tabName.replace(/\s+/g, "-")}`;
    if (first) {
      button.classList.add("active");
      button.setAttribute("aria-selected", "true");
    } else {
      button.setAttribute("aria-selected", "false");
    }
    button.setAttribute("aria-controls", `panel-${tabName.replace(/\s+/g, "-")}`);
    tabNav.appendChild(button);

    const panel = el("div", "tab-panel");
    panel.id = `panel-${tabName.replace(/\s+/g, "-")}`;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id);
    if (first) {
      panel.classList.add("active");
    }
    panel.append(...tabCards);
    tabWrapper.appendChild(panel);

    first = false;
  });

  // If only one tab with content, don't show tabs
  if (hasMultipleTabs <= 1) {
    const singlePanel = tabWrapper.querySelector(".tab-panel");
    if (singlePanel) {
      singlePanel.classList.remove("tab-panel");
      singlePanel.classList.add("cards");
      singlePanel.removeAttribute("hidden");
      singlePanel.style.display = "block";
      return singlePanel;
    }
    return tabWrapper;
  }

  // Tab switching
  tabNav.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      tabNav.querySelectorAll("button").forEach((btn) => {
        btn.classList.remove("active");
        btn.setAttribute("aria-selected", "false");
      });
      button.classList.add("active");
      button.setAttribute("aria-selected", "true");

      tabWrapper.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.remove("active");
      });
      const activePanel = tabWrapper.querySelector(`#panel-${button.dataset.tab.replace(/\s+/g, "-")}`);
      if (activePanel) {
        activePanel.classList.add("active");
      }
    });
  });

  tabContainer.appendChild(tabNav);
  tabContainer.appendChild(tabWrapper);

  return tabContainer;
}

function plyLabel(ply, previous) {
  if (!previous || previous.color === "Black") {
    return `${ply.moveNumber}.`;
  }
  return "";
}

function plyCaption(ply) {
  return `${ply.moveNumber}${ply.color === "White" ? "." : "..."} ${ply.san}`;
}

function becausePhrase(ply) {
  return ply.color === "White"
    ? `${ply.san} is beneficial because it`
    : `${ply.san} is good because it`;
}

function renderBecause(target, ply, bind = noBind) {
  target.replaceChildren();
  if (!ply) return;
  if (ply.purposes && ply.purposes.length) {
    const reasons = el("div", "because");
    reasons.append(el("p", "because-title", becausePhrase(ply)));
    reasons.append(factList(ply.purposes, "because-list", bind, ply.fenBefore));
    target.append(reasons);
  }
  if (ply.weaknesses && ply.weaknesses.length) {
    const weak = el("div", "because because-weak");
    weak.append(el("p", "because-title", `${ply.san} weaknesses: it`));
    weak.append(factList(ply.weaknesses, "because-list weak-list", bind, ply.fenBefore));
    target.append(weak);
  }
}

function pvLine(candidate, bind = noBind, onSelect) {
  const row = el("div", "pv-line");
  const plies = candidate.linePlies && candidate.linePlies.length
    ? candidate.linePlies
    : [];
  if (!plies.length) {
    row.append(el("span", "pv", candidate.line));
    return row;
  }
  const buttons = [];
  const mark = (selected) => {
    buttons.forEach((button) => {
      const active = button === selected;
      button.classList.toggle("current", active);
      button.setAttribute("aria-current", String(active));
    });
  };
  plies.forEach((ply, index) => {
    const prefix = plyLabel(ply, plies[index - 1]);
    if (prefix) row.append(el("span", "pv-num", prefix));
    const move = el("button", "pv-move", ply.san);
    move.type = "button";
    bind(move, ply.cue, ply.fenBefore, plyCaption(ply));
    move.addEventListener("click", (event) => {
      event.stopPropagation();
      mark(move);
      if (onSelect) onSelect(ply);
    });
    buttons.push(move);
    row.append(move);
  });
  if (onSelect && buttons[0]) mark(buttons[0]);
  return row;
}

function bestLineCard(view, bind = noBind, onSelectPly) {
  const best = view.candidates[0];
  const box = card("Explaining the best line of Stockfish NNUE", "nnue-line");
  const intro = el("div", "best-line");
  const bullet = el("div", "best-line-row");
  bullet.append(el("span", "best-dot", "•"));
  const becauseHost = el("div", "because-host");
  const start = best.linePlies && best.linePlies[0]
    ? best.linePlies[0]
    : {
        san: best.san,
        color: view.turn,
        purposes: view.purposes,
        weaknesses: [],
        fenBefore: view.fen,
      };
  bullet.append(pvLine(best, bind, (ply) => {
    renderBecause(becauseHost, ply, bind);
    if (onSelectPly) onSelectPly(ply);
  }));
  intro.append(bullet);
  box.append(intro);
  renderBecause(becauseHost, start, bind);
  box.append(becauseHost);
  return box;
}

function positionCards(view, depth, bind = noBind, onSelectPly) {
  const cards = [];

  // Hero/summary card - always shown
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

  const best = view.candidates[0];
  if (best) {
    cards.push(bestLineCard(view, bind, onSelectPly));
  }

  // Alternate lines stay available, but the first line lives in the explainer.
  if (view.candidates.length > 1) {
    const box = card(`Other lines for ${view.perspective}`);
    const lines = el("div", "lines");
    view.candidates.slice(1).forEach((c) => {
      const line = el("div", "line");
      line.append(el("span", "move", `${c.rank}. ${c.san}`));
      line.append(el("span", "score", scoreText(c.evalCp, c.mate)));
      line.append(pvLine(c, bind));
      bind(line, c.cue);
      lines.append(line);
    });
    box.append(lines);
    cards.push(box);
  }

  // Threats and related
  const threats = [];
  if (view.threatBefore) {
    threats.push({ text: `Before: ${view.threatBefore.text}`, cue: view.threatBefore.cue });
  }
  if (view.threatAfterBest) {
    const best = view.candidates[0] ? view.candidates[0].san : "the best move";
    threats.push({
      text: `After ${best}: ${view.threatAfterBest.text}`,
      cue: view.threatAfterBest.cue,
    });
  }
  if (threats.length || view.neutralised.length || view.created.length) {
    const box = card("Threats");
    if (threats.length) box.append(factList(threats, null, bind));
    if (view.neutralised.length) {
      box.append(el("h3", null, "This move defuses"));
      box.append(factList(view.neutralised, "defused", bind));
    }
    if (view.created.length) {
      box.append(el("h3", null, "This move concedes"));
      box.append(factList(view.created, "conceded", bind));
    }
    cards.push(box);
  }

  // Tactics
  if (view.tactics.length) {
    const box = card("Tactics on the board");
    box.append(factList(view.tactics, null, bind));
    cards.push(box);
  }

  // Hanging material
  if (view.hanging.length) {
    const box = card("Loose material");
    box.append(
      factList(
        view.hanging.map((h) => ({
          text: `${h.piece} on ${h.square} falls to ${h.captureSan} (${evalText(h.lossCp)})`,
          cue: h.cue,
        })),
        null,
        bind
      )
    );
    cards.push(box);
  }

  // Observations
  if (view.observations.length) {
    const box = card("Pay attention to");
    box.append(factList(view.observations, null, bind));
    cards.push(box);
  }

  // Piece roles
  if (view.roles.length) {
    const box = card(`Piece roles for ${view.perspective}`);
    box.append(factList(view.roles, null, bind));
    cards.push(box);
  }

  // Concepts
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
      bind(row, c.cue);
      kv.append(row);
    });
    box.append(kv);
    cards.push(box);
  }

  // NNUE contributions
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
      bind(row, c.cue);
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

function renderGame(target, data, bind = noBind) {
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
        cell.title = `${moveLabel(move)} — ${evalText(cp)}`;
        // Hovering the graph replays that move on the board it was played on.
        bind(cell, move.cue, move.fenBefore, `${moveLabel(move)} · ${evalText(cp)}`);
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
  data.sides.forEach((side) => sides.append(sideCard(side, bind)));
  target.append(sides);
}

function sideCard(side, bind = noBind) {
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
    box.append(moveList(side.turningPoints, bind));
  } else {
    box.append(el("p", "note", "No inaccuracies or worse."));
  }

  if (side.goodMoves.length) {
    box.append(el("h3", null, "Good moves"));
    box.append(moveList(side.goodMoves, bind));
  }

  return box;
}

function stat(value, label) {
  const box = el("div", "stat");
  box.append(el("span", "n", value));
  box.append(el("span", "l", label));
  return box;
}

function moveList(moves, bind = noBind) {
  const list = el("div", "moves");
  moves.forEach((move) => {
    const row = el("div", "move-row");
    row.append(el("span", "num", `${move.moveNumber}${move.mover === "White" ? "." : "..."}`));
    row.append(el("span", "san", move.san));
    row.append(el("span", `verdict-chip v-${move.verdict}`, move.verdict));
    row.append(el("span", "why", explainMove(move)));
    bind(row, move.cue, move.fenBefore, moveLabel(move));
    list.append(row);
  });
  return list;
}

function moveLabel(move) {
  return `${move.moveNumber}${move.mover === "White" ? "." : "..."} ${move.san}`;
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

/* ---------------- theme ---------------- */

const THEME_KEY = "decodex-theme";

/* Light and dark, remembered per browser.
 *
 * The stored choice wins over the system preference, since a visitor who has
 * pressed the button has said what they want. With nothing stored the OS
 * setting decides, and the page follows it if it changes.
 */
function wireTheme() {
  const button = $("theme-toggle");
  const system = window.matchMedia("(prefers-color-scheme: light)");
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch {
    /* Private browsing can refuse storage; the toggle still works per page. */
  }

  function apply(theme) {
    const light = theme === "light";
    document.documentElement.dataset.theme = light ? "light" : "dark";
    button.setAttribute("aria-pressed", String(light));
    // The label names the theme the button switches to, not the current one.
    $("theme-label").textContent = light ? "Dark" : "Light";
    $("theme-icon").textContent = light ? "◑" : "◐";
    button.title = light ? "Switch to dark" : "Switch to light";
  }

  apply(stored || (system.matches ? "light" : "dark"));

  system.addEventListener("change", (event) => {
    if (!stored) apply(event.matches ? "light" : "dark");
  });

  button.addEventListener("click", () => {
    stored = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    try {
      localStorage.setItem(THEME_KEY, stored);
    } catch {
      /* Not persisting is acceptable; the current page still switches. */
    }
    apply(stored);
  });
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

function showLinePly(board, ply, { turn } = {}) {
  const after = ply.fenAfter || ply.fenBefore;
  const before = ply.fenBefore || after;
  board.lastMove = ply.uci
    ? { from: ply.uci.slice(0, 2), to: ply.uci.slice(2, 4) }
    : null;
  // Draw the position after the clicked ply, with the move's arrow measured
  // on the position it was played from.
  board.setPosition(after);
  board.showCue(ply.cue, before);
  if (turn) {
    const side = (after.split(" ")[1] === "b") ? "Black" : "White";
    turn.textContent = `${side} to move · ${plyCaption(ply)}`;
  }
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
      board.clearCue();
      renderPositionViews(report, data.views, data.depth, cueBinder(board), (ply) => {
        showLinePly(board, ply, { turn: $("pos-turn") });
      });
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
  const board = new Board($("game-board"));
  const note = $("game-board-note");

  fillRange($("game-depth"), 6, limits.maxGameDepth, Math.min(10, limits.maxGameDepth));
  board.setPosition(START_FEN);

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
      board.clearCue();
      renderGame(
        report,
        data,
        cueBinder(board, (label) => {
          note.textContent = label || "Hover a move to see it";
        })
      );
      note.textContent = "Hover a move to see it";
      $("game-eval").textContent = "";
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
      renderPositionViews(report, data.views, data.depth, cueBinder(board), (ply) => {
        showLinePly(board, ply);
      });
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
      // A review points at earlier positions, so the board says which one it is
      // showing rather than silently contradicting the game state.
      const live = $("play-status-text").textContent;
      renderGame(
        report,
        data,
        cueBinder(board, (label) => {
          $("play-status-text").textContent = label ? `showing ${label}` : live;
        })
      );
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
  wireTheme();
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
