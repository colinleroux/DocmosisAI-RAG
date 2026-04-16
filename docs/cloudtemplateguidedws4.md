# Docmosis Cloud Template Reference (AI-Optimized)

```yaml
product: Docmosis
version: DWS4 (2025)
document_type: Technical Specification / Syntax Reference
author: Docmosis Pty Ltd
core_delimiters: "<< >>"
expression_delimiters: "<<{ }>>"
variable_prefix: "$" or "var_"
```

---

## 1. Global Syntax & Parsing Rules

### 1.1 Field Identification
* **Standard Fields:** Identified by `<<` and `>>`.
* **Strict Spacing:** A single space is permitted (e.g., `<< fieldName >>`), but multiple spaces or missing characters cause the engine to treat the field as static text.
* **Case Sensitivity:** Tag names must match the provided data structure exactly.
* **Null Handling:** If a data item is missing or null, the field is removed from the output document by default.

### 1.2 Error Management
* **Dev Mode:** Injects red-text errors and footnotes directly into the generated document for troubleshooting.
* **Prod Mode:** Aborts generation and returns a formal error code; no document is produced.

---

## 2. Logic & Control Flow

### 2.1 Conditional Content (cs_)
Controls visibility of content based on boolean values or logical expressions.

| Tag | Logic Rule |
| :--- | :--- |
| `<<cs_name>>` | Includes content if "name" is true or non-null. |
| `<<cs_{expr}>>` | Includes content if the expression evaluates to true. |
| `<<else>>` | Provides alternative content if the initial `cs_` is false. |
| `<<es_>>` | Required marker to close a conditional section. |

**Behavioral Note:** If a control tag (`<<cs_`, `<<else>`, `<<es_`) appears on its own line, the entire line is removed to prevent empty vertical space in the output.

### 2.2 Optional Paragraphs (op:)
* **Syntax:** `<<op:fieldName>>`.
* **Rule:** If the data for `fieldName` is blank or null, the entire paragraph—including static text and the paragraph marker (¶)—is deleted.

---

## 3. Expression Engine & Functions

### 3.1 Mathematical Precedence
1. `( )` Parentheses
2. `+`, `-`, `!` (Unary/Not)
3. `*`, `/`, `%` (Multiplication, Division, Modulus)
4. `+`, `-` (Binary Addition, Subtraction)
5. `<`, `<=`, `>`, `>=` (Comparisons)
6. `=`, `!=` (Equality)
7. `&&`, `||` (Boolean And/Or)

### 3.2 Common Functions
* **Logic:** `ifBlank(key, default)`, `map(key, t1, r1, ..., default)`.
* **Text:** `titleCase(str)`, `substring(str, start, end)`, `split(str, char, index)`.
* **Numeric:** `numFormat(val, format, locale)`, `round(num, places)`, `numToText(val)`.
* **Date:** `dateFormat(val, outFormat, inFormat, locale)`, `dateAdd(date, amt, units)`.

---

## 4. Iteration & Data Arrays

### 4.1 Repeating Sections (rs_ / rr_)
* **Block Repeat (`rs_`):** Repeats general document content (paragraphs, images).
* **Row Repeat (`rr_`):** Repeats rows within a table.
* **Column Control (`cc_`):** Conditionally removes a table column; table width remains constant.

### 4.2 Built-in Iteration Variables
* `<<$itemidx>>`: Current zero-based index (0, 1, 2...).
* `<<$itemnum>>`: Current one-based count (1, 2, 3...).
* `<<$size>>`: Total number of items in the current array.

### 4.3 Advanced Directives
* **Stepping:** `<<rs_items:stepN>>` creates variables `$i1` through `$iN` for multi-column layouts.
* **Sorting:** `:sort(field)`, `:sortNum(field)`, `:sortDate(field)`.
* **Filtering:** `<<rs_items:filter(expression)>>` only repeats items meeting the criteria.

---

## 5. Visual Assets & Formatting

### 5.1 Images
Images are identified by bookmarks (Word) or names (LibreOffice) using these prefixes:
* `img_`: Standard substitution.
* `imgfit_`: Resizes to fit placeholder while maintaining aspect ratio.
* `imgstretch_`: Forces image to match placeholder dimensions.

### 5.2 Barcodes & QR Codes
* **Barcodes:** Use `<<barcode:name:type>>`. Supported: Code128, Code39, ITF14, IMB.
* **QR Codes:** Use `<<qrcode:name:value>>`. Configurable settings include `dpi` and `ec` (Error Correction).

---

## 6. Document Architecture

### 6.1 Template Combination
* **Merging:** `<<ref:subtemplate.docx>>` embeds content. Sub-templates inherit master styling.
* **Coordination:** `<<coordinator:>>` renders multiple templates as independent documents, often joined as a single PDF.
* **Dynamic Ref:** `<<refLookup:key>>` determines which template to pull based on data.

### 6.2 Scoping Variables
* `<<$top>>`: Global root context.
* `<<$parent>>`: One level up from current context.
* `<<$this>>`: Current context.

### 6.3 Diagnostic Dumps
* `<<dump:$top>>`: Injects the raw data structure (JSON/XML) into the document for debugging.

---