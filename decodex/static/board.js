"use strict";

/* Pure board helpers: no DOM, no network.
 *
 * Kept apart from app.js so they can be tested directly under node. Square
 * colour and FEN expansion are exactly the sort of off-by-one arithmetic that
 * looks fine in a screenshot and is wrong, so they are checked against
 * python-chess in the test suite rather than by eye.
 */

const FILES = "abcdefgh";

/* Whether a square is light.
 *
 * a1 is dark, and a1 is fileIndex 0, rank 1, so a square is light exactly when
 * fileIndex + rank is even.
 */
function isLightSquare(fileIndex, rank) {
  return (fileIndex + rank) % 2 === 0;
}

/* Expand the placement field of a FEN into 8 rows of 8, rank 8 first.
 *
 * Returns null for anything that does not describe a full board, so a bad FEN
 * fails visibly instead of drawing a ragged grid.
 */
function expandFen(fen) {
  const placement = String(fen).trim().split(/\s+/)[0];
  if (!placement) return null;
  const rows = placement.split("/");
  if (rows.length !== 8) return null;

  const grid = [];
  for (const row of rows) {
    const line = [];
    for (const ch of row) {
      if (ch >= "1" && ch <= "8") {
        for (let i = 0; i < Number(ch); i += 1) line.push(null);
      } else if ("pnbrqkPNBRQK".includes(ch)) {
        line.push(ch);
      } else {
        return null;
      }
    }
    if (line.length !== 8) return null;
    grid.push(line);
  }
  return grid;
}

/* The 64 squares in drawing order: left to right, top to bottom.
 *
 * White's view starts at a8 and ends at h1; Black's is the exact reverse. Each
 * entry carries the file index and rank so callers do not have to redo the
 * arithmetic that this function exists to get right.
 */
function boardOrder(flipped) {
  const cells = [];
  for (let row = 0; row < 8; row += 1) {
    const rank = flipped ? row + 1 : 8 - row;
    for (let col = 0; col < 8; col += 1) {
      const fileIndex = flipped ? 7 - col : col;
      cells.push({
        square: FILES[fileIndex] + rank,
        fileIndex,
        rank,
        light: isLightSquare(fileIndex, rank),
        // The rank label goes on the near edge, the file label on the bottom.
        showRank: fileIndex === (flipped ? 7 : 0),
        showFile: rank === (flipped ? 8 : 1),
      });
    }
  }
  return cells;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FILES, isLightSquare, expandFen, boardOrder };
}
