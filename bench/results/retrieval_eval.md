# R-1: retrieval on 30 questions (2 full lectures, real Whisper transcripts)

| Method | Recall@5 | Own words (17) | Paraphrases (13) | MRR | Median latency |
|---|---|---|---|---|---|
| bm25 | 0.97 | 1.00 | 0.92 | 0.88 | 0.8 ms |
| vector | 0.97 | 1.00 | 0.92 | 0.89 | 8.1 ms |
| hybrid | 1.00 | 1.00 | 1.00 | 0.94 | 8.0 ms |

| Question | Kind | BM25 | Vector | Hybrid |
|---|---|---|---|---|
| What is the definition of declarative knowledge? | words | 1 | 1 | 1 |
| What is imperative knowledge? | words | 1 | 1 | 1 |
| How do you find the square root of a number starting from a guess? | words | 1 | 1 | 1 |
| How is the new guess computed in the square root algorithm? | words | 1 | 1 | 1 |
| What are the three parts of a recipe? | words | 1 | 1 | 1 |
| How does the recipe know when to stop? | paraphrase | 1 | 1 | 1 |
| Why can't a calculator be used to send email? | paraphrase | 1 | 1 | 1 |
| What changed with stored program computers? | words | 1 | 1 | 1 |
| What does the ALU do? | words | 1 | 1 | 1 |
| What does the program counter do? | words | 1 | 1 | 1 |
| Who showed that six primitives are enough to compute anything? | words | 1 | 1 | 1 |
| If something can be programmed in Python, can it be done in other languages? | paraphrase | 1 | 1 | 1 |
| What is an example of bad syntax in English? | words | 1 | 1 | 1 |
| What does static semantics mean? | words | 1 | 1 | 1 |
| Can a sentence have more than one meaning? | words | 1 | 1 | 1 |
| How did she choose the person who wins the prize? | paraphrase | 1 | – | 2 |
| Could I damage my laptop by experimenting with commands? | paraphrase | 3 | 1 | 1 |
| Why should other people be able to understand my code? | paraphrase | 1 | 1 | 1 |
| What happens inside the machine while it runs a program step by step? | paraphrase | 2 | 1 | 1 |
| Why don't we write programs using only Turing's handful of commands? | paraphrase | 3 | 1 | 1 |
| Formally, what is a computational problem? | words | 1 | 1 | 1 |
| Can one input have several correct answers? | paraphrase | 1 | 2 | 1 |
| How do we describe a problem without listing the answer for every input? | paraphrase | 1 | 1 | 1 |
| Why must two students share a birthday if there are more than 365 of them? | words | 1 | 1 | 1 |
| Why should an algorithm work for a class of any size? | paraphrase | 1 | 2 | 2 |
| What is an algorithm? | words | 3 | 1 | 1 |
| How does the birthday algorithm work? | words | 1 | 2 | 1 |
| Does an algorithm have to give exactly one output for each input? | paraphrase | 1 | 1 | 1 |
| How can we show the algorithm is right for any number of students? | paraphrase | – | 5 | 3 |
| What do we need for an inductive proof? | words | 1 | 1 | 1 |