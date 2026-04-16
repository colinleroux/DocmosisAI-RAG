# **Docmosis Support**

Absolutely — this is a good moment to step back and *frame what you’ve actually built*. What you have now is **real, working AI infrastructure**, not a demo, and being able to explain it clearly (to yourself or management) is important.

Below is a **plain-English summary** you can reuse internally.

---

# DaiS (Docmosis AI Support) — Current State Summary

## 1. What is working right now

You have built a **fully local, offline AI support system** with these components:

### 1.1 Local LLM (Language Model)

* **Model:** `dolphin3`
* **Type:** Transformer-based language model
* **Where it runs:** Inside an Ollama container on your machine
* **What it does:**

  * Takes a question + context
  * Generates a natural-language answer
  * Does **not** have internet access
  * Does **not** see data unless you explicitly give it context

This model is responsible for **wording, explanations, and structure**, not for “knowing” Docmosis by itself.

---

### 1.2 Embedding model (for search)

* **Model:** `nomic-embed-text`
* **Purpose:** Convert text into numeric vectors
* **Used for:**

  * Searching documentation semantically (meaning-based search)
  * Matching questions to relevant document sections

This model **does not generate text**. It only produces vectors for similarity comparison.

---

### 1.3 RAG (Retrieval-Augmented Generation)

Your system uses **RAG**, which means:

> The AI answers questions using *retrieved documentation*, not its own memory.

**How it works end-to-end:**

1. Documentation PDFs are ingested
2. Text is extracted per page
3. Text is split into chunks
4. Each chunk is embedded (converted into vectors)
5. Chunks are stored in **Qdrant** (vector database)
6. When a question is asked:

   * The question is embedded
   * The most relevant chunks are retrieved
   * Those chunks are passed to the LLM
   * The LLM answers **using only that context**

This is why DaiS can say *where* an answer came from (citations).

---

### 1.4 Vector database (Qdrant)

* Stores:

  * Embedded document chunks
  * Metadata (file name, page number, chunk index)
* Used to:

  * Quickly find relevant documentation sections
  * Enable traceable citations like:

    ```
    Cloud-Template-Guide.pdf#page:12:chunk:1
    ```

Qdrant contains **no AI logic** — it’s a high-performance search index.

---

## 2. Key AI terminology (in practical terms)

### 2.1 Training vs Tuning vs RAG

#### Training (from scratch)

* Building a model by feeding it billions of words
* Requires massive compute and data
* **You are NOT doing this**

#### Fine-tuning (adapting a model)

* Adjusting an existing model with examples
* Teaches:

  * Tone
  * Domain patterns
  * Common error → fix mappings
* **You are NOT doing this yet**

#### RAG (what you are doing)

* No model weights are changed
* Knowledge stays in documents
* Model only *uses* retrieved text
* Safer, faster, easier to maintain

**For support use cases, RAG is usually preferred before fine-tuning.**

---

### 2.2 Chunk size (what it means)

**Chunk size** = how much text is grouped together before embedding.

In your system:

* Text is split into chunks of ~1,200 characters (with overlap)

**Why chunking matters:**

* Too small → context is fragmented
* Too large → search becomes vague and slow

Good chunking:

* Keeps related concepts together
* Allows precise retrieval

Think of chunks as **index cards** created from your documentation.

---

### 2.3 Chunk overlap (why it exists)

* Adjacent chunks share some text (e.g. 200 characters)
* Prevents losing meaning at chunk boundaries

Without overlap:

* Important sentences might be split in half
* Retrieval becomes unreliable

---

### 2.4 `top_k` (very important)

**`top_k` = how many chunks are retrieved per question**

Example:

* `top_k = 5`
* The 5 most relevant documentation chunks are retrieved

**Trade-offs:**

* Low `top_k` → faster, but may miss context
* High `top_k` → more context, but slower and noisier

Typical values:

* Small docs: `3–5`
* Large PDFs: `6–10`

You are currently using this exactly as intended.

---

### 2.5 Citations

Citations are built from metadata stored during ingestion:

```
filename.pdf#page:X:chunk:Y
```

This allows:

* Verifying answers
* Building trust
* Debugging retrieval accuracy

This is **critical for internal support use**.

---

## 3. What DaiS is (and is not)

### What DaiS *is*

* An internal AI support assistant
* A documentation explainer
* A semantic search + explanation system
* Fully offline and SOC-friendly
* Controlled and auditable

### What DaiS is *not*

* Not autonomous
* Not customer-facing
* Not a replacement for support engineers
* Not a source of truth (docs are)

---

## 4. Why this architecture is strong

* 🔒 **Security:** No external APIs, no data leakage
* 📄 **Grounded:** Answers tied to documentation
* 🧠 **Explainable:** You can see what it used
* 🔁 **Maintainable:** Update docs, re-ingest, done
* 🧪 **Low risk:** No model retraining required

This is why this exact architecture is used widely in enterprise support tooling.

---

## 5. Natural next steps (when you’re ready)

In increasing order of complexity:

1. Improve PDF cleanup (remove headers/footers)
2. Tune chunk size per doc type
3. Add structured answer templates (cause → evidence → fix)
4. Add fine-tuning (LoRA) **only if needed**
5. Add UI (internal only)

But importantly:

> **You already have a real MVP.**

---

### One-sentence summary you can reuse

> *DaiS is a local, offline AI support assistant that uses semantic search over Docmosis documentation and a small language model to produce grounded, explainable answers without exposing data to external services.*

If you want, next I can:

* Help you turn this into **internal documentation**
* Prepare **management-friendly wording**
* Or guide you through **accuracy tuning** so answers get even sharper
