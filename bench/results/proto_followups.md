# Step-0 prototype: the assistant's understand step

Live position 07:25 in Python · Lecture 1.

**LLM plan alone: 7/12 correct; with the deterministic guards: 7/12.**

## 1. "wait what did she mean just now" PASS

```json
{
 "intent": "explain_recent",
 "standalone_question": "What did she mean just now?",
 "refers_to": {
  "span": [
   415,
   445
  ],
  "term": null,
  "previous_answer": false
 },
 "depth": "brief",
 "style": "simpler",
 "ambiguous": false
}
```

## 2. "explain that again but simpler" PASS

Earlier turns: *user:* what is a computer good at according to her? / *assistant:* From the lecture: a computer does two things: it performs calculations, about a billion per second [07:00], and it remembers the results in memory [07:10].

```json
{
 "intent": "explain_recent",
 "standalone_question": "Explain that again but simpler",
 "refers_to": {
  "span": [
   415,
   445
  ],
  "term": null,
  "previous_answer": true
 },
 "depth": "normal",
 "style": "simpler",
 "ambiguous": false
}
```

## 3. "summarise the last 5 minutes" PASS

```json
{
 "intent": "summarise",
 "standalone_question": "summarise the last 5 minutes",
 "refers_to": {
  "span": [
   145,
   445
  ],
  "term": null,
  "previous_answer": false
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

## 4. "what does modular mean? short answer please" PASS

```json
{
 "intent": "define",
 "standalone_question": "What does modular mean?",
 "refers_to": {
  "span": null,
  "term": "modular",
  "previous_answer": false
 },
 "depth": "brief",
 "style": "simpler",
 "ambiguous": false
}
```

LLM plan alone: standalone question lacks 'programming skill'

## 5. "tell me more about the second one" MISS

Earlier turns: *user:* what are the three big things we should get out of the course? / *assistant:* Knowledge of concepts [03:50], programming skills [04:00], and problem solving, practised through the problem sets [04:10].

```json
{
 "intent": "explain_recent",
 "standalone_question": "tell me more about the second one",
 "refers_to": {
  "span": null,
  "term": null,
  "previous_answer": true
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

Misses: standalone question lacks 'programming skill'

LLM plan alone: span None (want ~[185, 215])

## 6. "go back to the part about not being afraid of breaking the computer, why did she say that?" MISS

```json
{
 "intent": "ask",
 "standalone_question": "Why did the lecturer say not to be afraid of breaking the computer?",
 "refers_to": {
  "span": null,
  "term": null,
  "previous_answer": false
 },
 "depth": "normal",
 "style": "simpler",
 "ambiguous": false
}
```

Misses: span None (want ~[185, 215])

LLM plan alone: span None (want ~[0, 445])

## 7. "quiz me on what we've covered so far" MISS

```json
{
 "intent": "quiz",
 "standalone_question": "quiz me on what we've covered so far",
 "refers_to": {
  "span": null,
  "term": null,
  "previous_answer": false
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

Misses: span None (want ~[0, 445])

## 8. "how fast was she speaking in the last minute?" PASS

```json
{
 "intent": "data",
 "standalone_question": "how fast was she speaking in the last minute?",
 "refers_to": {
  "span": [
   385,
   445
  ],
  "term": null,
  "previous_answer": false
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

LLM plan alone: ambiguous False (want True)

## 9. "is it better than the other one?" MISS

```json
{
 "intent": "ask",
 "standalone_question": "Is it better than the other one?",
 "refers_to": {
  "span": [
   390,
   400
  ],
  "term": null,
  "previous_answer": false
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

Misses: ambiguous False (want True)

## 10. "who won the football world cup in 2022?" PASS

```json
{
 "intent": "other",
 "standalone_question": "who won the football world cup in 2022?",
 "refers_to": {
  "span": null,
  "term": null,
  "previous_answer": false
 },
 "depth": "brief",
 "style": "same",
 "ambiguous": false
}
```

## 11. "what is recursion?" PASS

```json
{
 "intent": "define",
 "standalone_question": "What is recursion?",
 "refers_to": {
  "span": null,
  "term": "recursion",
  "previous_answer": false
 },
 "depth": "normal",
 "style": "same",
 "ambiguous": false
}
```

LLM plan alone: intent explain_recent (want define/ask); previous_answer False

## 12. "ok and in a lot more detail please" MISS

Earlier turns: *user:* what's declarative knowledge? / *assistant:* Background: declarative knowledge is knowledge stated as facts. (Not covered yet in this lecture.)

```json
{
 "intent": "explain_recent",
 "standalone_question": "Please explain declarative knowledge in a lot more detail.",
 "refers_to": {
  "span": null,
  "term": "declarative knowledge",
  "previous_answer": false
 },
 "depth": "detailed",
 "style": "more_technical",
 "ambiguous": false
}
```

Misses: intent explain_recent (want define/ask)
