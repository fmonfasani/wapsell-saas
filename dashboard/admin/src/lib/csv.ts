// Minimal CSV parser for the catalog upload flow. Handles double-quoted
// fields with embedded commas/newlines because real-world catalog exports
// (Tiendanube, Shopify, MercadoLibre) wrap product descriptions in quotes
// when they contain commas. Anything beyond that — escapes, BOM, mixed
// encodings — is out of scope; we'd reach for PapaParse before reinventing.
//
// Contract:
//   - First non-empty line is the header. Headers are trimmed and lowercased.
//   - Subsequent non-empty lines become rows.
//   - The `content` column is required (free-text fact for the agent).
//   - Every other column becomes a `metadata` key→value pair on the row.
//     Empty cells are skipped, not stored as "".

import type { CatalogFactIn } from "./types";

export class CsvParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CsvParseError";
  }
}

export interface ParsedCsv {
  headers: string[];
  rows: CatalogFactIn[];
}

export function parseCatalogCsv(text: string): ParsedCsv {
  const stripped = text.replace(/^﻿/, ""); // strip BOM if Excel saved it
  const lines = splitLogicalLines(stripped);
  if (lines.length === 0) {
    throw new CsvParseError("El archivo CSV está vacío.");
  }

  const headers = parseCsvLine(lines[0]).map((h) => h.trim().toLowerCase());
  const contentIdx = headers.indexOf("content");
  if (contentIdx === -1) {
    throw new CsvParseError(
      "El CSV debe tener una columna llamada 'content' con la descripción del producto/política.",
    );
  }

  const rows: CatalogFactIn[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim() === "") continue;
    const cols = parseCsvLine(line);
    const content = (cols[contentIdx] ?? "").trim();
    if (content === "") continue; // empty content row — skip silently

    const metadata: Record<string, string> = {};
    for (let j = 0; j < headers.length; j++) {
      if (j === contentIdx) continue;
      const v = (cols[j] ?? "").trim();
      if (v !== "") metadata[headers[j]] = v;
    }

    rows.push({ content, metadata });
  }

  if (rows.length === 0) {
    throw new CsvParseError(
      "El CSV no tiene filas con contenido. Verificá que la columna 'content' tenga texto.",
    );
  }

  return { headers, rows };
}

// Splits the file into logical lines respecting quoted newlines.
// `"hello\nworld"` is one logical line; an unquoted newline starts a new one.
function splitLogicalLines(text: string): string[] {
  const out: string[] = [];
  let buf = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      // Doubled quote inside a quoted field is an escape, not a delimiter.
      if (inQuotes && text[i + 1] === '"') {
        buf += '""';
        i++;
        continue;
      }
      inQuotes = !inQuotes;
      buf += ch;
      continue;
    }
    if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && text[i + 1] === "\n") i++; // CRLF
      out.push(buf);
      buf = "";
      continue;
    }
    buf += ch;
  }
  if (buf !== "") out.push(buf);
  return out;
}

// Parses a single CSV line into columns. Handles `"a,b",c` and `"a""b"` (escaped quote).
function parseCsvLine(line: string): string[] {
  const cols: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
        continue;
      }
      inQuotes = !inQuotes;
      continue;
    }
    if (ch === "," && !inQuotes) {
      cols.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  cols.push(cur);
  return cols;
}
