# Docmosis Unified Guide (V9)
## Full Reference + Support Playbook + RAG (Expanded Chunks)

---

# PART C: RAG CHUNKS (FULLY EXPANDED)

## [CHUNK-001: FIELD_BASIC]
Docmosis fields insert data into templates.

Syntax:
<<fieldName>>

Rules:
- Case-sensitive
- Must match data exactly
- Invalid syntax is treated as plain text

Example:
Template:
<<name>>

Data:
{
  "name": "John"
}

Output:
John

Common Failures:
- Case mismatch (Name vs name)
- Extra spaces << name >>
- Missing >>


---

## [CHUNK-002: NULL_HANDLING]
If a field value is null or missing:
- The field is removed
- The line remains unless controlled

Example:
Name: <<name>>

If null → "Name: " (blank)

Fix:
- Use <<op:name>>
- Or wrap in <<cs_>>


---

## [CHUNK-003: CONDITIONAL_BASIC]
Conditionals control visibility.

Syntax:
<<cs_condition>>
Content
<<es_>>

Behavior:
- True → included
- False → removed

Example:
<<cs_isActive>>
Active User
<<es_>>


---

## [CHUNK-004: CONDITIONAL_EXPRESSIONS]
Supports expressions.

Examples:
<<cs_{amount > 100}>>
<<cs_{name = 'John'}>>

Rules:
- Strings require quotes
- Numeric comparisons use >, <, =

Failure Causes:
- Type mismatch
- Missing quotes


---

## [CHUNK-005: CONDITIONAL_LINE_REMOVAL]
If control tags are alone on a line:
- Entire line is removed

Example:
<<cs_name>>

Prevents blank spacing


---

## [CHUNK-006: REPEAT_BASIC]
Repeats iterate arrays.

Syntax:
<<rs_items>>
<<name>>
<<es_>>

Data must be:
{
  "items": []
}

Failure:
- Not an array → only one item shown


---

## [CHUNK-007: REPEAT_CONTEXT]
Inside a repeat:
- Context becomes current item

Example:
items[0].name → <<name>>

Implication:
- No need for full path inside loop


---

## [CHUNK-008: DOT_NOTATION]
Access nested data directly.

Example:
<<hotel.floor[0].roomName>>

Use when:
- single access needed
- no loop required

Failure:
- incorrect structure path


---

## [CHUNK-009: DATA_SCOPING]
Access different levels of data.

<<$top.field>> → root
<<$parent.field>> → one level up
<<$this>> → current item

Use case:
Nested loops referencing outer values


---

## [CHUNK-010: OPTIONAL_PARAGRAPH]
Syntax:
<<op:name>>

Behavior:
- Removes entire paragraph if null

Best for:
- labels + values together


---

## [CHUNK-011: EXPRESSIONS]
Syntax:
<<{expression}>>

Supports:
- math
- logic
- functions

Example:
<<{price * qty}>>


---

## [CHUNK-012: DATE_FORMAT]
Function:
<<{dateFormat(dateVal, 'dd/MM/yyyy')}>>  

Warning:
- Input must be ISO or defined

Example:
<<{dateFormat(dateVal, 'dd/MM/yyyy', 'yyyy-MM-dd')}>>  

Failure:
- Wrong input format → blank output


---

## [CHUNK-013: VARIABLES]
Set:
<<$var = value>>

Use:
<<$var>>

Safe:
<<$?var>>

Tip:
- Use safe variables to prevent errors


---

## [CHUNK-014: IMAGE_BEHAVIOUR]
Images are controlled by template placeholders.

Rules:
- Placeholder defines size
- Source image does NOT control dimensions

Implication:
- Wrong placeholder = distortion


---

## [CHUNK-015: IMAGE_STRATEGY]
Options:
- Base64
- URL
- Stock images

Best practice:
- Use /uploadImage

Reason:
- smaller payload
- faster rendering


---

## [CHUNK-016: IMAGE_FAILURES]
Common causes:
- Wrong bookmark name
- Floating image
- Missing data


---

## [CHUNK-017: TABLE_ALTERNATING_ROWS]
Alternating rows determined by:
- background color of template rows

Not controlled by code

Fix:
- adjust template styling


---

## [CHUNK-018: LIST_BEHAVIOUR]
Auto reindex:
- removed items renumber automatically

Continue lists:
<<list:continue>>


---

## [CHUNK-019: PERFORMANCE]
Issues caused by:
- large base64 images
- large payloads

Fix:
- use uploaded images


---

## [CHUNK-020: DEBUGGING]
Steps:
1. Enable devMode
2. Inspect output
3. Use <<dump:$top>>
4. Validate JSON

---

# END
