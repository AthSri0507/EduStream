# Prototype §11: study-guide notes, Algorithms · Lecture 1 (6.006), 00:00-20:00


## Update 0: 00:00-01:30

openai/gpt-oss-120b, 1.052 s, 1116+110 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Course Overview",
   "text": "The class is Introduction to Algorithms, taught by Jason Ku with co‑instructors Eric Domen and Justin Solomon. The course focuses on solving computational problems and also emphasizes communicating solutions.",
   "terms": [
    "computational problems"
   ],
   "background": null,
   "quote": "the course is about algorithms ... teaching you to solve computational problems"
  }
 ],
 "info": null
}
```

Validation: `quote_near_verbatim`; `term_dropped:'computational problems'`


## Update 1: 01:30-03:00

openai/gpt-oss-120b, 1.897 s, 1185+118 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Communication and Proof",
   "text": "The course emphasizes proving correctness and arguing efficiency of algorithms, which means you must be able to demonstrate that a solution works and is optimal. It also stresses communicating these ideas clearly to others, not just to a computer, through extensive writing.",
   "terms": [
    "correctness",
    "efficiency"
   ],
   "background": null,
   "quote": "prove correct... argue efficiency... communication of these ideas"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'correctness'`; `term_dropped:'efficiency'`


## Update 2: 03:00-04:30

openai/gpt-oss-120b, 0.759 s, 1260+153 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Computational problem",
   "text": "A computational problem is defined as a binary relation between a set of possible inputs and a set of possible outputs, where for each input the relation specifies which outputs are correct. The input space may contain many elements and the output space can be larger than the input space.",
   "terms": [
    "computational problem",
    "binary relation"
   ],
   "background": null,
   "quote": "what a problem is a binary relation between these inputs and outputs"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'computational problem'`; `term_dropped:'binary relation'`


## Update 3: 04:30-06:00

openai/gpt-oss-20b, 0.804 s, 1367+152 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Computational Problem",
   "text": "A computational problem is a binary relation between a set of possible inputs and a set of possible outputs, where for each input the relation specifies which outputs are correct. The lecturer illustrated this with a graph of inputs and outputs, where edges represent the relation. Instead of listing every input–output pair, we usually define a predicate that can check whether a given output is correct for a given input.",
   "terms": [
    "computational problem",
    "binary relation",
    "predicate"
   ],
   "background": null,
   "quote": "a binary relation between a set of possible inputs and a set of possible outputs"
  }
 ],
 "info": null
}
```

Validation: `located_by_support`; `repeat: 'A computational problem is a binary relation between a set o'`; `filler: 'The lecturer illustrated this with a graph of inputs and out'`; `term_dropped:'computational problem'`; `term_dropped:'binary relation'`; `term_dropped:'predicate'`


## Consolidation 00:00-06:00 (open) -> cut at 06:00, llm

openai/gpt-oss-120b, 1.894 s, 2458+574 tokens (cached)

```json
{
 "topics": [
  {
   "n": 1,
   "title": "Course Goals: Solving, Proving, and Communicating",
   "starts_at": "00:00"
  },
  {
   "n": 2,
   "title": "Formal Definition of a Computational Problem",
   "starts_at": "03:00"
  }
 ],
 "elements": [
  {
   "topic": 1,
   "kind": "para",
   "lead": "Course focus",
   "text": "The class teaches you to solve computational problems, to prove that your solutions are correct, and to argue their efficiency. It also emphasizes communicating those solutions clearly to other people, not just to a computer, through extensive writing.",
   "terms": [
    "computational problem",
    "prove correctness",
    "argue efficiency"
   ],
   "quote": "It's about algorithms... solving computational problems... prove correct... argue efficiency... communication of these ideas."
  },
  {
   "topic": 1,
   "kind": "para",
   "lead": "Writing emphasis",
   "text": "You will do a lot more writing in this theory class than coding, because the ability to convey correctness and efficiency in written form is a central skill.",
   "terms": [],
   "quote": "you'll be doing a lot more writing than you do in a lot of your other courses."
  },
  {
   "topic": 2,
   "kind": "para",
   "lead": "Problem as binary relation",
   "text": "A computational problem is a binary relation between a set of possible inputs and a set of possible outputs, specifying for each input which outputs are correct. The input space may have many elements and the output space can be larger than the input space.",
   "terms": [
    "binary relation",
    "input space",
    "output space"
   ],
   "quote": "a problem is a binary relation between these inputs and outputs... for each input, I specify which of these outputs is correct."
  },
  {
   "topic": 2,
   "kind": "para",
   "lead": "Predicate definition",
   "text": "Rather than enumerating every input–output pair, we define a problem by a predicate that can check whether a given output is correct for a given input. For example, to verify an index containing the value 5, we simply look at that array position and compare it to 5.",
   "terms": [
    "predicate"
   ],
   "quote": "we usually define a problem by specifying some kind of predicate... I can check whether that output is correct or not."
  }
 ],
 "questions": [
  {
   "topic": 1,
   "q": "What three abilities does the course aim to develop beyond solving problems?",
   "answer": "Proving correctness, arguing efficiency, and communicating solutions in writing."
  },
  {
   "topic": 2,
   "q": "How is a computational problem formally described?",
   "answer": "As a binary relation between inputs and outputs, often given by a predicate that checks output correctness for each input."
  }
 ],
 "in_progress_from": null
}
```

Validation: `located_by_support`; `term_dropped:'computational problem'`; `term_dropped:'prove correctness'`; `term_dropped:'argue efficiency'`; `term_dropped:'binary relation'`; `term_dropped:'input space'`; `term_dropped:'output space'`; `quote_near_verbatim`; `term_dropped:'predicate'`


## Update 4: 06:00-07:30

openai/gpt-oss-120b, 0.751 s, 1263+155 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Predicates for problem definition",
   "text": "We express computational problems using predicates rather than specific small instances, allowing a general formulation. For example, the predicate asks whether any two students share the same birthday, which becomes false only when the number of students exceeds the number of possible birthdays.",
   "terms": [
    "predicate"
   ],
   "background": null,
   "quote": "we're putting it in terms of predicates, because in general, we don't really want to talk about small instances of problems"
  }
 ],
 "info": null
}
```

Validation: `sentence_unsupported(0.38): 'For example, the predicate asks whether any two students share the sam'`; `term_dropped:'predicate'`


## Update 5: 07:30-09:00

openai/gpt-oss-20b, 0.84 s, 1235+136 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "General Problem Scope",
   "text": "We focus on problems that accept arbitrarily sized inputs, not just a fixed classroom. The goal is to design algorithms that work for any input size, from a few hundred students to a billion, such as checking for birthday matches in a large database.",
   "terms": [
    "arbitrarily sized inputs"
   ],
   "background": null,
   "quote": "I want an algorithm that can change. It can accept an arbitrary size input, right?"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'arbitrarily sized inputs'`


## Update 6: 09:00-10:30

openai/gpt-oss-20b, 0.852 s, 1291+205 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Algorithm Definition",
   "text": "An algorithm is a fixed-size machine or procedure that, given an input, generates an output. The output must be one of the correct outputs specified by the problem; otherwise the algorithm is incorrect. Thus an algorithm can be viewed as a function mapping inputs to a single correct output.",
   "terms": [
    "algorithm",
    "function"
   ],
   "background": null,
   "quote": "an algorithm is a little different than a problem of problem specification"
  },
  {
   "kind": "para",
   "lead": "Correctness Requirement",
   "text": "If an algorithm produces an output that is not among the acceptable outputs for a given input, it fails to satisfy the correctness condition. Therefore, correctness is defined by the algorithm’s ability to produce only valid outputs for all inputs.",
   "terms": [
    "correctness"
   ],
   "background": null,
   "quote": "if it generates an output, it better be one of these correct outputs"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'function'`; `sentence_unsupported(0.27): 'If an algorithm produces an output that is not among the acceptable ou'`; `cascade: 'Therefore, correctness is defined by the algorithm’s ability'`; `paragraph_dropped(0/2)`


## Update 7: 10:30-12:00

openai/gpt-oss-20b, 1.352 s, 1410+234 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Birthday‑matching algorithm",
   "text": "The algorithm assigns each student a unique number and interviews them sequentially. For each interview it records the birthday and scans the existing record for a match. If a match is found it returns success and stops; otherwise it appends the new birthday to the record and continues.",
   "terms": [
    "birthday‑matching algorithm"
   ],
   "background": null,
   "quote": "I'm going to interview you one by one. I'm going to say, what's your birthday?"
  },
  {
   "kind": "example",
   "title": "Linear‑search birthday check",
   "text": "During the interview of student i the algorithm searches the list of i−1 birthdays. If none match, it appends the new birthday and proceeds to student i+1.",
   "steps": [
    "Interview student i",
    "Record birthday",
    "Scan previous birthdays",
    "If match: return success",
    "Else: append birthday"
   ],
   "code": null,
   "quote": "I'm going to put in some kind of record. . . . . . . ."
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'birthday‑matching algorithm'`; `item_unsupported(0.33): 'Scan previous birthdays'`


## Consolidation 06:00-12:00 (open) -> cut at 12:00, llm

openai/gpt-oss-120b, 2.489 s, 2733+849 tokens (cached)

```json
{
 "topics": [
  {
   "n": 3,
   "title": "Predicate‑Based Formulation of Computational Problems",
   "starts_at": "06:00"
  },
  {
   "n": 4,
   "title": "Algorithms as Input‑Output Functions",
   "starts_at": "09:00"
  },
  {
   "n": 5,
   "title": "Linear‑Search Algorithm for Birthday Matching",
   "starts_at": "11:00"
  }
 ],
 "elements": [
  {
   "topic": 3,
   "kind": "para",
   "lead": "General problem description",
   "text": "We express computational problems using predicates rather than concrete small instances, which lets the problem be defined for any size of input. For example, the predicate “∃ two students with the same birthday” applies whether the class has ten or ten million members.",
   "terms": [
    "predicate"
   ],
   "quote": "we're putting it in terms of predicates, because in general, we don't really want to talk about small instances of problems"
  },
  {
   "topic": 3,
   "kind": "para",
   "lead": "Scaling the input space",
   "text": "If we enlarge the birthday space by adding the birth hour, the input domain grows, and the likelihood of a match decreases; the problem remains interesting as long as the input size can exceed the square of the number of participants.",
   "terms": [
    "input space"
   ],
   "quote": "as long as that space is larger than something like the square of the number of u, right?"
  },
  {
   "topic": 4,
   "kind": "para",
   "lead": "Algorithm as a fixed‑size procedure",
   "text": "An algorithm is a fixed‑size machine or procedure that, given an input, produces an output. The output must be one of the correct outputs specified by the problem; otherwise the algorithm is incorrect.",
   "terms": [
    "algorithm"
   ],
   "quote": "an algorithm is a little different than a problem of problem specification"
  },
  {
   "topic": 4,
   "kind": "para",
   "lead": "Algorithm as a function",
   "text": "Formally, an algorithm can be viewed as a function that maps each input from the problem’s domain to a single output, and that output must be correct for the given input.",
   "terms": [
    "function"
   ],
   "quote": "an algorithm is some kind of function that takes these inputs, maps it to a single output, and that output better be correct"
  },
  {
   "topic": 5,
   "kind": "para",
   "lead": "Sequential interview procedure",
   "text": "The proposed birthday‑matching algorithm numbers the students, then interviews them one by one, recording each birthday in a list. After each new entry it scans the existing list for a matching birthday; if a match is found it returns success and stops, otherwise it appends the new birthday and continues.",
   "terms": [
    "record"
   ],
   "quote": "I'm going to put you guys in some order, okay? I'm going to give each of you a number"
  },
  {
   "topic": 5,
   "kind": "example",
   "title": "Linear‑search birthday check",
   "text": "During the interview of student i the algorithm searches the list of i‑1 recorded birthdays. If none match, it appends the new birthday and proceeds to student i+1.",
   "steps": [
    "Interview student i",
    "Record birthday",
    "Search existing list for a match",
    "If match, return success and stop",
    "Else, append birthday and continue"
   ],
   "quote": "If I find... to match, right? Then I return, yay, I found a parent, I can stop"
  }
 ],
 "questions": [
  {
   "topic": 3,
   "q": "Why do we use predicates instead of specific instances when defining a computational problem?",
   "a": "Because predicates allow the problem to be defined for any input size, not just a small concrete case."
  },
  {
   "topic": 4,
   "q": "What condition must an algorithm’s output satisfy to be considered correct?",
   "a": "It must be one of the correct outputs specified by the problem for that input."
  },
  {
   "topic": 5,
   "q": "What does the linear‑search birthday algorithm do when it finds a matching birthday?",
   "a": "It returns success and stops the procedure."
  }
 ],
 "in_progress_from": null
}
```

Validation: `term_dropped:'predicate'`; `quote_near_verbatim`; `term_dropped:'input space'`; `term_dropped:'function'`; `logistics_paragraph: 'The proposed birthday‑matching algorithm numbers t'`; `example_text_repeats_steps`; `short_topic_merged:'Linear‑Search Algorithm for Birthday Matching' -> 'Algorithms as Input‑Output Functions' (1 kept, 0 repeated)`


## Update 8: 12:00-13:30

openai/gpt-oss-20b, 0.778 s, 1125+182 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Birthday‑matching algorithm",
   "text": "The algorithm iterates over students in some order, maintaining a record of seen birthdays. For each student, it checks whether the birthday is already in the record; if so, it returns the pair of matching students. If not, it adds the birthday to the record. After all students are processed, if no match was found, it returns that there is none.",
   "terms": [
    "birthday problem",
    "record",
    "pair"
   ],
   "background": null,
   "quote": "for birthday problem. What's the algorithm here?"
  },
  {
   "kind": "remember",
   "text": "The algorithm is a concrete example of a predicate‑based formulation of a computational problem.",
   "quote": "Okay, so that's a statement of an algorithm."
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'birthday problem'`; `term_dropped:'record'`; `term_dropped:'pair'`; `remember_demoted: 'The algorithm is a concrete example of a predicate‑based for'`; `sentence_unsupported(0.25): 'The algorithm is a concrete example of a predicate‑based formulation o'`; `paragraph_dropped(0/1)`


## Update 9: 13:30-15:00

openai/gpt-oss-20b, 1.306 s, 1309+138 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Algorithm as Pure Function",
   "text": "An algorithm must be a pure function: it maps each input to exactly one output, with no side effects. The lecturer emphasized that this is the mathematical definition of a function used when defining an algorithm. The algorithm is a procedure that takes an input, produces an output, and must be correct.",
   "terms": [
    "pure function",
    "algorithm"
   ],
   "background": null,
   "quote": "Pure function does an algorithm have to be a pure function in the mathematical..."
  }
 ],
 "info": null
}
```

Validation: `filler: 'The lecturer emphasized that this is the mathematical defini'`; `term_dropped:'pure function'`


## Update 10: 15:00-16:30

openai/gpt-oss-20b, 0.711 s, 1421+136 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Proof of Correctness",
   "text": "To prove the algorithm correct for any number of students, the lecturer proposes using mathematical induction. By showing the base case for a small number of students and then proving that if the algorithm works for n students it also works for n+1, the correctness is established for all n.",
   "terms": [
    "induction"
   ],
   "background": null,
   "quote": "What kind of technique do I use to prove such things, yeah. Induction right"
  }
 ],
 "info": null
}
```

Validation: `filler: 'To prove the algorithm correct for any number of students, t'`; `sentence_unsupported(0.36): 'By showing the base case for a small number of students and then provi'`; `paragraph_dropped(0/1)`


## Update 11: 16:30-18:00

openai/gpt-oss-20b, 0.919 s, 1348+215 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Constant‑size Code",
   "text": "We write a constant‑size piece of code that can handle arbitrarily large inputs. The code must loop, recurse, or repeat lines to process the input. This necessity leads to recursion and induction as core techniques.",
   "terms": [
    "recursion",
    "induction"
   ],
   "background": null,
   "quote": "We do in this class what we do as a computer scientist is We write a constant size piece of code, right?"
  },
  {
   "kind": "para",
   "lead": "Inductive Proof Setup",
   "text": "An inductive proof requires a base case, a predicate hypothesis to be maintained, and an inductive step that shows the hypothesis holds for the next case.",
   "terms": [
    "inductive proof",
    "predicate hypothesis"
   ],
   "background": null,
   "quote": "So how can we set up this induction? What do I need for an inductive proof?"
  }
 ],
 "info": null
}
```

Validation: `sentence_unsupported(0.33): 'This necessity leads to recursion and induction as core techniques.'`; `term_dropped:'recursion'`; `term_dropped:'induction'`; `term_dropped:'inductive proof'`; `term_dropped:'predicate hypothesis'`


## Consolidation 12:00-18:00 (open) -> cut at 18:00, llm

openai/gpt-oss-20b, 1.558 s, 2477+741 tokens

```json
{
 "topics": [
  {
   "n": 5,
   "title": "Birthday‑Matching Algorithm",
   "starts_at": "12:00"
  },
  {
   "n": 6,
   "title": "Algorithm as a Pure Function",
   "starts_at": "13:00"
  },
  {
   "n": 7,
   "title": "Constant‑Size Code for Arbitrary Inputs",
   "starts_at": "14:00"
  },
  {
   "n": 8,
   "title": "Inductive Proof Setup",
   "starts_at": "16:20"
  }
 ],
 "elements": [
  {
   "topic": 5,
   "kind": "para",
   "lead": "Algorithm description",
   "text": "The algorithm iterates over students in some order, maintaining a record of seen birthdays. For each student it checks whether the birthday is already in the record; if so, it returns the pair of matching students. If not, it adds the birthday to the record. After all students are processed, if no match was found, it returns that there is none.",
   "terms": [
    "birthday‑matching algorithm"
   ],
   "quote": "for birthday problem. What's the algorithm here? ... return a pair. Otherwise. You add a new student to record. ... if I go through everybody, and I haven't found a match yet, I'm going to return that there is none."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Pure function requirement",
   "text": "An algorithm must be a pure function: it maps each input to exactly one output, with no side effects. The algorithm is a procedure that takes an input, produces an output, and must be correct.",
   "terms": [
    "pure function"
   ],
   "quote": "Pure function does an algorithm have to be a pure function in the mathematical... sense as in it needs to map to a single output."
  },
  {
   "topic": 7,
   "kind": "para",
   "lead": "Constant‑size code",
   "text": "We write a constant‑size piece of code that can handle arbitrarily large inputs. The code must loop, recurse, or repeat lines to process the input.",
   "terms": [
    "constant‑size code"
   ],
   "quote": "We write a constant size piece of code, right? take on any arbitrarily large size input, right? If the input can be arbitrarily large, but our code is small, then that code needs to loop or recurse or repeat some of these lines of code in order to just read that output."
  },
  {
   "topic": 8,
   "kind": "para",
   "lead": "Inductive proof setup",
   "text": "An inductive proof requires a base case, a predicate hypothesis to be maintained, and an inductive step that shows the hypothesis holds for the next case.",
   "terms": [
    "inductive proof"
   ],
   "quote": "So how can we set up this induction? What do I need for an inductive proof? Sure base case we need a base case we need some kind of a predicate, yeah, but we need some kind of statement of a hypothesis of something that should be maintained, right? And then we need to have an inductive step."
  }
 ],
 "questions": [
  {
   "topic": 5,
   "q": "What does the birthday‑matching algorithm return when it finds a match?",
   "answer": "It returns the pair of matching students."
  },
  {
   "topic": 6,
   "q": "Why must an algorithm be a pure function?",
   "answer": "Because it must map each input to exactly one output with no side effects."
  },
  {
   "topic": 7,
   "q": "Why does constant‑size code need to loop or recurse?",
   "answer": "To process arbitrarily large inputs."
  },
  {
   "topic": 8,
   "q": "What are the three components of an inductive proof?",
   "answer": "Base case, predicate hypothesis, inductive step."
  }
 ],
 "in_progress_from": null
}
```

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-120b', 'local_budget')]

Validation: `quote_near_verbatim`; `term_dropped:'birthday‑matching algorithm'`; `term_dropped:'pure function'`; `quote_near_verbatim`; `term_dropped:'constant‑size code'`; `term_dropped:'inductive proof'`; `short_topic_merged:'Birthday‑Matching Algorithm' -> 'Algorithms as Input‑Output Functions' (1 kept, 0 repeated)`; `short_topic_merged:'Algorithm as a Pure Function' -> 'Algorithms as Input‑Output Functions' (1 kept, 0 repeated)`


## Update 12: 18:00-19:30

openai/gpt-oss-20b, 1.644 s, 1259+136 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Inductive Hypothesis",
   "text": "The inductive hypothesis states that after interviewing the first K students, if a matching pair exists among those K, the algorithm has already returned that pair. This guarantees that when all students are processed, a pair will be returned whenever one exists, and none otherwise.",
   "terms": [
    "inductive hypothesis"
   ],
   "background": null,
   "quote": "Let's say after I've interviewed the first K students, if there was a match in those first K students."
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'inductive hypothesis'`


## Update 13: 19:30-20:00

openai/gpt-oss-120b, 1.034 s, 1058+144 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Inductive Hypothesis",
   "text": "If a matching pair is found among the first K students, the algorithm returns that pair immediately, so the hypothesis holds for each incremental step. Consequently, after processing all N students, the algorithm will have returned a pair exactly when one exists, and will return none otherwise.",
   "terms": [
    "inductive hypothesis"
   ],
   "background": null,
   "quote": "If a matching pair is found among the first K students, the algorithm returns that pair"
  }
 ],
 "info": null
}
```

Validation: `not_grounded(0.31): 'Inductive Hypothesis If a matching pair is found among the f'`


## Consolidation 18:00-20:00 (closed) -> cut at 20:00, llm

openai/gpt-oss-20b, 1.454 s, 1526+358 tokens

```json
{
 "topics": [
  {
   "n": 6,
   "title": "Inductive Proof of Correctness",
   "starts_at": "18:00"
  }
 ],
 "elements": [
  {
   "topic": 6,
   "kind": "para",
   "lead": "Inductive Hypothesis",
   "text": "The inductive hypothesis states that after interviewing the first K students, if a matching pair exists among those K, the algorithm has already returned that pair. This guarantees that when all students are processed, a pair will be returned whenever one exists, and none otherwise.",
   "terms": [
    "inductive hypothesis"
   ],
   "background": null,
   "quote": "The inductive hypothesis states that after interviewing the first K students, if a matching pair exists among those K, the algorithm has already returned that pair."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Generalization for Induction",
   "text": "To generalize the concept for induction, the lecturer says that after interviewing the first K students, if there was a match in those first K students, the algorithm must have returned a pair. Maintaining this property ensures correctness at the end of the process.",
   "terms": [],
   "background": null,
   "quote": "If there was a match in those first K students, the algorithm must have returned a pair."
  }
 ],
 "questions": [
  {
   "topic": 6,
   "q": "What does the inductive hypothesis assert about the algorithm after interviewing the first K students?",
   "answer": "That if a matching pair exists among those K students, the algorithm has already returned that pair."
  }
 ]
}
```

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-120b', 'local_budget')]

Validation: `located_by_support`; `term_dropped:'inductive hypothesis'`; `located_by_support`; `filler: 'To generalize the concept for induction, the lecturer says t'`
