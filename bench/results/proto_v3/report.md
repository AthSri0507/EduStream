# Prototype rev 2: structured live drafts + consolidation, Python · Lecture 1 (Bell), 00:00-12:30


## Update 0: 00:00-01:30

openai/gpt-oss-120b, 0.853 s, 1255+198 tokens (cached)

```json
{
 "ops": [
  {
   "op": "topic",
   "title": "Introduction",
   "starts_at": "00:00"
  },
  {
   "op": "info",
   "text": "Lecture recorded for OCW; seating choice affects background visibility; course info and computation overview will follow.",
   "quote": "lecture will be recorded for OCW"
  }
 ]
}
```

Validation: `topic_names_current`


## Update 1: 01:30-03:00

openai/gpt-oss-120b, 1.336 s, 1286+446 tokens (cached)

```json
{
 "ops": [
  {
   "op": "info",
   "text": "Slides will be posted before each lecture; download them and have them open for in‑class exercises."
  },
  {
   "op": "new",
   "type": "list",
   "title": "Tips for succeeding in the course",
   "items": [
    "Read problem sets as soon as they are released",
    "Let terminology sink in",
    "Connect lecture content to problem‑set terms"
   ],
   "quote": "helped me get through my first, very first programming course"
  },
  {
   "op": "new",
   "type": "important",
   "title": "Practice is essential: the more you practice, the better you get at it.",
   "quote": "The more you practice, the better you get at it"
  }
 ]
}
```

Validation: `located_by_support`; `item_unsupported(0.33): 'Let terminology sink in'`; `item_unsupported(0.33): 'Connect lecture content to problem‑set terms'`


## Update 2: 03:00-04:30

openai/gpt-oss-20b, 0.718 s, 1328+160 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "key_idea",
   "title": "Course roadmap: concepts, skills, problem‑solving",
   "items": [
    "Knowledge of concepts",
    "Programming skills",
    "Problem‑solving through problem sets"
   ],
   "quote": "So this is pretty much a road map of all of 6 Triple 1 or 600 as i've just explained it. So there's three big things we want you to get out of this course."
  }
 ]
}
```

Validation: all kept


## Update 3: 04:30-06:00

openai/gpt-oss-20b, 0.997 s, 1361+429 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "list",
   "title": "Three main sections of the course",
   "items": [],
   "quote": "The things we're going to learn in this class can be divided into basically three different sections."
  },
  {
   "op": "extend",
   "block": "u3b0",
   "items": [
    "Learning how to program – data structures and representation",
    "Control flow – decisions and branching",
    "Writing good code – style, readability, modularity"
   ],
   "quote": "So the first one is related to these first two items here. So it's really about learning how to program. So learning how to program is, part of it is figuring out what objects to create. You'll learn about these. How do you represent knowledge with data structures? That's sort of the broad term for that. And then as you're writing programs, you need to, programs Aren't just linear. Sometimes programs jump They make decisions. There's some control flow to programs. So that's what the second line is going to be about. The second big part of this course. This is a little bit more abstract, and it deals with how do you write good code, good style. code that's readable."
  }
 ]
}
```

Validation: `extend_converted:other_topic`


## Consolidation 00:00-06:00 (open) -> cut at 06:00, llm

openai/gpt-oss-120b, 2.223 s, 2332+760 tokens (cached)

```json
{
 "topics": [
  {
   "n": 1,
   "title": "Course success strategies and overall roadmap",
   "starts_at": "00:20",
   "revisits": null
  },
  {
   "n": 2,
   "title": "Core content areas: programming fundamentals, control flow, and code style",
   "starts_at": "04:40",
   "revisits": null
  }
 ],
 "blocks": [
  {
   "topic": 1,
   "type": "list",
   "title": "Tips for succeeding in the course",
   "items": [
    "Read problem sets as soon as they are released",
    "Make sure terminology sinks in as you encounter it"
   ],
   "quote": "was I just read the P-sets as soon as they came out, made sure that the terminology kind of just sunk in"
  },
  {
   "topic": 1,
   "type": "important",
   "title": "Practice is essential",
   "quote": "If you're new to programming, I think the keyword is practice, so it's like math or reading. The more you practice, the better you get at it."
  },
  {
   "topic": 1,
   "type": "key_idea",
   "title": "Course roadmap: concepts, skills, problem‑solving",
   "items": [
    "Knowledge of concepts",
    "Programming skills",
    "Problem‑solving through problem sets"
   ],
   "quote": "There are three big things we want you to get out of this course... the knowledge of concepts... programming skills... we teach you how to solve problems through the p‑sets"
  },
  {
   "topic": 2,
   "type": "list",
   "title": "Three main sections of the course",
   "items": [
    "Learning how to program: data structures and representation",
    "Control flow: decisions and branching",
    "Writing good code: style, readability, modularity"
   ],
   "quote": "The things we're going to learn in this class can be divided into basically three different sections... learning how to program... control flow... writing good code"
  },
  {
   "topic": 2,
   "type": "key_idea",
   "title": "Learning how to program involves data structures",
   "items": [
    "Represent knowledge with appropriate data structures"
   ],
   "quote": "Learning how to program is part of figuring out what objects to create... how do you represent knowledge with data structures?"
  },
  {
   "topic": 2,
   "type": "key_idea",
   "title": "Control flow enables decisions and branching",
   "items": [
    "Programs are not just linear; they can make decisions"
   ],
   "quote": "Programs aren't just linear. Sometimes programs jump. They make decisions. There's some control flow to programs."
  },
  {
   "topic": 2,
   "type": "key_idea",
   "title": "Good code style emphasizes readability and modularity",
   "items": [
    "Write code that is well‑organized, modular, and easy to understand"
   ],
   "quote": "When you write code, you want it to be readable and understandable by others, well‑organized, modular"
  }
 ],
 "questions": [
  {
   "topic": 1,
   "q": "What three outcomes does the course aim to give you?",
   "answer": "Knowledge of concepts, programming skills, and problem‑solving through problem sets."
  },
  {
   "topic": 2,
   "q": "Name the three core content areas the lecturer outlined for the course.",
   "answer": "Learning how to program (data structures), control flow (decisions/branching), and writing good code (style/readability/modularity)."
  }
 ],
 "in_progress_from": null
}
```

Validation: `located_by_support`; `quote_near_verbatim`; `quote_near_verbatim`; `located_by_support`; `short_topic_merged:'Core content areas: programming fundamentals, control flow, and code style' -> 'Course success strategies and overall roadmap' (4 blocks kept, 0 repeated)`


## Update 4: 06:00-07:30

openai/gpt-oss-120b, 1.284 s, 1269+325 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "key_idea",
   "title": "A computer performs calculations and stores results",
   "items": [
    "Performs many calculations rapidly",
    "Stores results in memory"
   ],
   "quote": "It performs calculations and it has to store them somewhere"
  },
  {
   "op": "new",
   "type": "definition",
   "term": "computer memory",
   "title": "Hardware used to store data and program results",
   "quote": "Store them in computer memory"
  },
  {
   "op": "new",
   "type": "important",
   "title": "Modern computers can execute about a billion calculations per second",
   "quote": "A billion calculations per second is probably not far off"
  }
 ]
}
```

Validation: `quote_near_verbatim`


## Update 5: 07:30-09:00

openai/gpt-oss-20b, 0.814 s, 1313+206 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "key_idea",
   "title": "Primitive operations are built into the language",
   "items": [
    "Addition, subtraction, multiplication, etc. are low‑level calculations"
   ],
   "quote": "things like addition, subtraction, multiplication, and so on"
  },
  {
   "op": "new",
   "type": "definition",
   "term": "Declarative knowledge",
   "title": "Statements of fact that describe the world",
   "quote": "The first type of knowledge is declarative knowledge. And those are things like statements of fact."
  },
  {
   "op": "new",
   "type": "important",
   "title": "Computers only do what you tell them to do",
   "quote": "Computers only know what you tell them. Computers only do what you tell them to do. They're not magical."
  }
 ]
}
```

Validation: all kept


## Update 6: 09:00-10:30

openai/gpt-oss-20b, 1.093 s, 1406+343 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "definition",
   "title": "Imperative knowledge is the recipe or the how to or the",
   "term": "imperative knowledge",
   "quote": "imperative knowledge is the recipe or the how to or the"
  },
  {
   "op": "new",
   "type": "definition",
   "title": "The IDE that we're using in this class is called anaconda",
   "term": "Anaconda IDE",
   "quote": "the IDE that we're using in this class is called anaconda"
  },
  {
   "op": "new",
   "type": "list",
   "title": "Steps to win a Google Cardboard before class ends",
   "items": [],
   "quote": "So step one, I think we've already done that."
  }
 ]
}
```

Validation: `term_not_in_transcript:'Anaconda IDE'`


## Update 7: 10:30-12:00

openai/gpt-oss-120b, 1.074 s, 1486+296 tokens (cached)

```json
{
 "ops": [
  {
   "op": "new",
   "type": "example",
   "title": "Using Python to pick a random responder",
   "items": [
    "import random",
    "random.randint(16,272) → 75"
   ],
   "quote": "I'm going to choose a random number between 16 and 272"
  }
 ]
}
```

Validation: all kept


## Consolidation 06:00-12:00 (open) -> cut at 12:00, llm

openai/gpt-oss-120b, 3.226 s, 2377+1297 tokens (cached)

```json
{
 "topics": [
  {
   "n": 2,
   "title": "What a computer does: calculations and memory",
   "starts_at": "07:00",
   "revisits": null
  },
  {
   "n": 3,
   "title": "Declarative vs imperative knowledge and a Python random‑selection example",
   "starts_at": "08:40",
   "revisits": null
  }
 ],
 "blocks": [
  {
   "topic": 2,
   "type": "key_idea",
   "title": "Computers perform calculations and store results",
   "items": [
    "Perform many calculations rapidly",
    "Store results in computer memory"
   ],
   "quote": "Mentally, it does two things. One, performs calculations... It performs these calculations and it has to store them somewhere, right?"
  },
  {
   "topic": 2,
   "type": "important",
   "title": "Modern computers can execute about a billion calculations per second",
   "quote": "A billion calculations per second is probably not far off."
  },
  {
   "topic": 2,
   "type": "definition",
   "term": "computer memory",
   "title": "Hardware used to store data and program results",
   "quote": "Store them in computer memory."
  },
  {
   "topic": 2,
   "type": "key_idea",
   "title": "Primitive operations are built into the language",
   "items": [
    "Addition, subtraction, multiplication, etc."
   ],
   "quote": "calculations that are built into the language... things like addition, subtraction, multiplication, and so on."
  },
  {
   "topic": 3,
   "type": "definition",
   "term": "Declarative knowledge",
   "title": "Statements of fact that describe the world",
   "quote": "The first type of knowledge is declarative knowledge. And those are things like statements of fact."
  },
  {
   "topic": 3,
   "type": "definition",
   "term": "Imperative knowledge",
   "title": "A recipe or sequence of steps describing how to achieve something",
   "quote": "imperative knowledge is the recipe or the how to or the ... of steps."
  },
  {
   "topic": 3,
   "type": "important",
   "title": "Computers only do what you tell them to do",
   "quote": "Computers only know what you tell them... Computers only do what you tell them to do."
  },
  {
   "topic": 3,
   "type": "example",
   "title": "Using Python to pick a random responder",
   "items": [
    "Import the random module",
    "Call random.randint(16,272)",
    "Get a result (e.g., 75)"
   ],
   "quote": "I'm going to choose a random number... random.randint(16,272) → 75"
  },
  {
   "topic": 3,
   "type": "list",
   "title": "Steps to win the Google Cardboard prize",
   "items": [
    "Sign up for the raffle",
    "Open the IDE (Anaconda)",
    "Choose a random number between the first and nth responder",
    "Find the matching responder in the sheet"
   ],
   "quote": "step one... open my IDE... choose a random number between 16 and 272"
  }
 ],
 "questions": [
  {
   "topic": 2,
   "q": "Why does the lecturer stress writing readable and organized code?",
   "answer": "Because if the code is a big mess you might not be able to understand or re‑understand what you were doing."
  },
  {
   "topic": 3,
   "q": "How do declarative and imperative knowledge differ?",
   "answer": "Declarative knowledge are statements of fact; imperative knowledge are step‑by‑step recipes describing how to achieve something."
  }
 ],
 "in_progress_from": null
}
```

Validation: `block_topic_by_time`; `quote_near_verbatim`; `item_unsupported(0.33): 'Import the random module'`


## Update 8: 12:00-12:30

openai/gpt-oss-120b, 0.823 s, 1060+95 tokens

```json
{
 "ops": [
  {
   "op": "new",
   "type": "example",
   "title": "Python random‑selection example",
   "items": [
    "Import random module",
    "Call random.choice or random.randint to get a random number",
    "Use the result in everyday code"
   ],
   "quote": "just lecturing just to find a random number"
  }
 ]
}
```

Validation: `item_unsupported(0.33): 'Import random module'`


## Consolidation 12:00-12:30 (closed) -> cut at 12:30, llm

openai/gpt-oss-120b, 1.115 s, 882+274 tokens

```json
{
 "topics": [
  {
   "n": 4,
   "title": "Python random‑selection example (revisit)",
   "starts_at": "12:00",
   "revisits": 3
  }
 ],
 "blocks": [
  {
   "topic": 4,
   "type": "example",
   "title": "Random selection with Python's random module",
   "items": [
    "Use random.choice(seq) to pick a random element from a sequence",
    "Or use random.randint(a,b) to get a random integer between a and b inclusive",
    "The returned value can be directly used in everyday code, e.g., for simple decisions"
   ],
   "quote": "Just lecturing just to find a random number, right?"
  },
  {
   "topic": 4,
   "type": "important",
   "title": "Apply Python's random functions in everyday tasks",
   "quote": "Try to use python wherever you can."
  }
 ],
 "questions": [
  {
   "topic": 4,
   "q": "What two main functions did the lecturer mention for obtaining random values in Python, and how do they differ?",
   "answer": "random.choice selects a random element from a sequence, while random.randint returns a random integer within a specified range."
  }
 ]
}
```

Validation: `item_unsupported(0.29): 'Use random.choice(seq) to pick a random element from a seque'`; `item_unsupported(0.33): 'Or use random.randint(a,b) to get a random integer between a'`; `item_unsupported(0.12): 'The returned value can be directly used in everyday code, e.'`; `question_unsupported(0.27)`; `short_topic_merged:'Python random‑selection example (revisit)' -> 'Declarative vs imperative knowledge and a Python random‑selection example' (2 blocks kept, 0 repeated)`
