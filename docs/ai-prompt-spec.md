# Local AI Prompt Contract — V1

## Purpose

Use a local Ollama model to analyze explicitly supplied prospect information and draft concise outreach.

## Input

The prompt may contain:

- company name
- contact name
- job title
- industry
- country
- employee count
- website URL
- supplied painpoint
- supplied evidence
- selected service
- selected message style

## Rules

1. Treat supplied data as the only factual source unless additional data has actually been retrieved by the application.
2. Never invent a business problem, customer behavior, technology stack, performance metric, review, or website observation.
3. Distinguish observed facts, user-supplied facts, inference and unknowns.
4. Keep outreach concise and specific.
5. Do not include fake familiarity or claims such as “I noticed” unless the application actually provided the observation.
6. Return JSON only when structured output is requested.

## Output schema

```json
{
  "problem": "string",
  "evidence": "string",
  "opportunity": "string",
  "recommended_service": "string",
  "confidence": 0.0,
  "message": "string"
}
```

`confidence` must be a number from 0.0 to 1.0. The application must validate the schema, message length and required fields before storing the draft.

## Message constraints

Default message: no more than 3 sentences.

The message should:

- identify a genuine supplied problem or carefully qualified opportunity;
- explain the relevant service/value;
- end with one clear CTA;
- avoid filler, fabricated evidence and excessive hype.

The prompt is a contract, not a substitute for application-side validation. The Python application remains responsible for rejecting malformed or unsafe AI output.
