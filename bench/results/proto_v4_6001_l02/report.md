# Prototype §11: study-guide notes, Python · Lecture 2 (Bell), 00:00-20:00


## Update 0: 00:00-01:30

openai/gpt-oss-20b, 0.682 s, 1175+92 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Computer fundamentals",
   "text": "A computer only executes instructions given by the programmer; it does not make spontaneous decisions. The programmer writes programs that tell the computer what to do.",
   "terms": [],
   "background": null,
   "quote": "a computer only does what it is told, right?"
  }
 ],
 "info": null
}
```

Validation: all kept


## Update 1: 01:30-03:00

openai/gpt-oss-20b, 0.992 s, 1242+225 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "String objects",
   "text": "Strings are a new object type that hold sequences of characters, including letters, digits, special characters, and spaces. They are created by enclosing the characters in quotation marks, either single or double, and the choice of quote type does not affect the value as long as it is consistent. The variable high is bound to the string \"hello there\" using the assignment operator, so subsequent references to high will yield that string value.",
   "terms": [
    "string",
    "assignment operator"
   ],
   "background": null,
   "quote": "strings are going to be sequences of characters"
  },
  {
   "kind": "para",
   "lead": "Variable binding",
   "text": "When a string is assigned to a variable, the variable becomes a reference to that string object. Python tracks the value of the variable, so any later use of the variable will retrieve the stored string.",
   "terms": [
    "variable binding"
   ],
   "background": null,
   "quote": "we're binding it to this variable named high"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'string'`; `term_dropped:'assignment operator'`; `term_dropped:'variable binding'`


## Update 2: 03:00-04:30

openai/gpt-oss-20b, 0.605 s, 1364+127 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "String concatenation",
   "text": "Concatenation joins two strings using the plus operator, producing a new string that is the sequence of the first string followed by the second. The operator does not insert any spaces automatically; a space must be added explicitly if desired.",
   "terms": [
    "concatenation",
    "plus operator"
   ],
   "background": null,
   "quote": "using this plus operator, which means put the strings together"
  }
 ],
 "info": null
}
```

Validation: `sentence_unsupported(0.38): 'The operator does not insert any spaces automatically; a space must be'`; `term_dropped:'concatenation'`; `term_dropped:'plus operator'`


## Update 3: 04:30-06:00

openai/gpt-oss-20b, 0.861 s, 1335+250 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "String repetition",
   "text": "Python allows the star operator to repeat a string a given number of times. When a string is multiplied by an integer, the interpreter concatenates that string to itself the specified number of times. In the example, the expression (\" \" + name) * 3 repeats the space and name three times, then concatenates the result with the greeting \"hello there\".",
   "terms": [
    "string repetition",
    "star operator"
   ],
   "background": null,
   "quote": "Python allows you to use the star operator, which is stands for multiplication between a string and a number."
  },
  {
   "kind": "example",
   "title": "Greeting repetition",
   "text": "The code creates a greeting by concatenating \"hello there\" with three repetitions of a space and a name. Printing the result outputs the greeting followed by the name repeated three times.",
   "steps": [],
   "code": "greeting = \"hello there\" + (\" \" + name) * 3",
   "quote": "So if i print that out. It's going to multiply the space with my name three times"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'string repetition'`; `term_dropped:'star operator'`


## Consolidation 00:00-06:00 (open) -> cut at 06:00, llm

openai/gpt-oss-20b, 1.546 s, 2683+818 tokens (cached)

```json
{
 "topics": [
  {
   "n": 1,
   "title": "String Objects",
   "starts_at": "00:00"
  },
  {
   "n": 2,
   "title": "String Concatenation",
   "starts_at": "03:00"
  },
  {
   "n": 3,
   "title": "String Repetition",
   "starts_at": "05:00"
  }
 ],
 "elements": [
  {
   "topic": 1,
   "kind": "para",
   "lead": "String Objects",
   "text": "Strings are a new object type that hold sequences of characters, including letters, digits, special characters, and spaces. They are created by enclosing the characters in quotation marks, either single or double, and the choice of quote type does not affect the value as long as it is consistent. The variable high is bound to the string \"hello there\" using the assignment operator, so subsequent references to high will yield that string value.",
   "terms": [
    "String",
    "quotation marks",
    "assignment operator"
   ],
   "quote": "strings are going to be sequences of characters and these characters can be anything"
  },
  {
   "topic": 1,
   "kind": "para",
   "lead": "Variable Binding",
   "text": "When a string is assigned to a variable, the variable becomes a reference to that string object. Python tracks the value of the variable, so any later use of the variable will retrieve the stored string.",
   "terms": [
    "variable binding"
   ],
   "quote": "we're binding it to this variable named high"
  },
  {
   "topic": 2,
   "kind": "para",
   "lead": "String Concatenation",
   "text": "Concatenation joins two strings using the plus operator, producing a new string that is the sequence of the first string followed by the second. The plus operator does not add any spaces implicitly; a space must be inserted manually if desired.",
   "terms": [
    "concatenation",
    "plus operator"
   ],
   "quote": "concatenation is really just a fancy word for using this plus operator"
  },
  {
   "topic": 2,
   "kind": "example",
   "title": "Greeting without Space",
   "text": "Printing the concatenation of high and name outputs \"hello thereAnna\" because no space was added.",
   "steps": [],
   "code": "print(high + name)",
   "quote": "Notice it prints out hello there, Anna. Right? There's no space."
  },
  {
   "topic": 2,
   "kind": "example",
   "title": "Greeting with Space",
   "text": "Adding a space string between high and name produces a proper greeting.",
   "steps": [],
   "code": "print(high + \" \" + name)",
   "quote": "concatenating the value of the variable high. a space, notice we're putting it in quotation marks, just a space, and then with name."
  },
  {
   "topic": 3,
   "kind": "para",
   "lead": "String Repetition",
   "text": "Python allows the star operator to repeat a string a given number of times. When a string is multiplied by an integer, the interpreter concatenates that string to itself the specified number of times.",
   "terms": [
    "star operator",
    "string repetition"
   ],
   "quote": "Python allows you to use the star operator, which is stands for multiplication between a string and a number"
  },
  {
   "topic": 3,
   "kind": "example",
   "title": "Repeated Greeting",
   "text": "The expression (\" \" + name) * 3 repeats the space and name three times, then concatenates the result with the greeting \"hello there\".",
   "steps": [],
   "code": "greeting = high + (\" \" + name) * 3\nprint(greeting)",
   "quote": "multiply whatever the result of this is by three. Okay? So if i print that out."
  }
 ],
 "questions": [
  {
   "topic": 1,
   "q": "What syntax creates a string object in Python?",
   "answer": "Enclosing characters in quotation marks, either single or double."
  },
  {
   "topic": 2,
   "q": "Does the plus operator automatically insert spaces between strings?",
   "answer": "No, it does not; a space must be added manually."
  },
  {
   "topic": 3,
   "q": "What does the star operator do when applied to a string and an integer?",
   "answer": "It repeats the string that many times."
  }
 ],
 "in_progress_from": null
}
```

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ['openai/gpt-oss-120b', 'local_budget']]

Validation: `term_dropped:'String'`; `term_dropped:'quotation marks'`; `term_dropped:'assignment operator'`; `term_dropped:'variable binding'`; `term_dropped:'concatenation'`; `term_dropped:'plus operator'`; `example_repeats_earlier`; `term_dropped:'star operator'`; `term_dropped:'string repetition'`; `short_topic_merged:'String Repetition' -> 'String Concatenation' (2 kept, 0 repeated)`


## Update 4: 06:00-07:30

openai/gpt-oss-120b, 1.052 s, 1223+140 tokens (cached)

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Print commas vs plus",
   "text": "Using commas inside print adds a space automatically between the values, while using the plus operator concatenates without inserting a space. The lecturer demonstrates this by printing a string and a variable with a comma versus using plus to join them.",
   "terms": [
    "print",
    "comma",
    "plus"
   ],
   "background": null,
   "quote": "If you use a comma, Python is going to automatically add a space"
  }
 ],
 "info": null
}
```

Validation: `filler: 'The lecturer demonstrates this by printing a string and a va'`; `term_dropped:'print'`; `term_dropped:'comma'`; `term_dropped:'plus'`


## Update 5: 07:30-09:00

openai/gpt-oss-20b, 0.915 s, 1248+204 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Commas vs Plus",
   "text": "Using commas in a print statement inserts a space automatically between each argument, which can be convenient when you want readable output. The plus operator concatenates strings without adding spaces, but every operand must be a string object, so numeric values must be converted with str().",
   "terms": [
    "print statement",
    "concatenation"
   ],
   "background": null,
   "quote": "Python's going to automatically insert a space for you"
  },
  {
   "kind": "para",
   "lead": "Conversion Requirement",
   "text": "When using the plus operator, Python performs exactly what you specify, so if you add a number to a string you must first convert the number to a string with str().",
   "terms": [
    "str() conversion"
   ],
   "background": null,
   "quote": "you have to convert all of your numbers to string objects"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'print statement'`; `term_dropped:'concatenation'`; `term_dropped:'str() conversion'`


## Update 6: 09:00-10:30

openai/gpt-oss-20b, 1.337 s, 1300+119 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "User Input",
   "text": "The input() function pauses execution and displays a prompt string, then returns whatever the user types as a string. When the user presses Enter, the input is captured and stored as a string value.",
   "terms": [
    "input()"
   ],
   "background": null,
   "quote": "the program is just going to stop and it's going to wait for the user to type in something and hit enter"
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'input()'`


## Update 7: 10:30-12:00

openai/gpt-oss-20b, 0.955 s, 1404+253 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "User Input as String",
   "text": "The input() function pauses execution and displays a prompt string, then returns whatever the user types as a string. Everything the user types in is made into a string object and bound to the variable text. When the user presses Enter, the input is captured and stored as a string value.",
   "terms": [
    "input()",
    "string object"
   ],
   "background": null,
   "quote": "the input() function pauses execution and displays a prompt string, then returns whatever the user types as a string"
  },
  {
   "kind": "para",
   "lead": "Casting to Numbers",
   "text": "If the user enters a number, it is still a string until cast. To work with numbers, cast by placing the desired type before the input, e.g., int(input(...)). This converts the typed value into an int if it is a valid numeric string. The same applies to float for floating point numbers.",
   "terms": [
    "casting",
    "int()",
    "float()"
   ],
   "background": null,
   "quote": "you cast by just putting... in this little bit right in front of the input"
  }
 ],
 "info": null
}
```

Validation: `located_by_support`; `repeat: 'The input() function pauses execution and displays a prompt '`; `repeat: 'When the user presses Enter, the input is captured and store'`; `term_dropped:'input()'`; `term_dropped:'string object'`; `term_dropped:'casting'`; `term_dropped:'int()'`; `term_dropped:'float()'`


## Consolidation 06:00-12:00 (open) -> cut at 12:00, fallback

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-120b', 'local_budget'), ('openai/gpt-oss-20b', 'local_budget')]

Validation: `fallback (all_failed)`


## Update 8: 12:00-13:30

openai/gpt-oss-20b, 0.767 s, 1198+129 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Casting Input",
   "text": "Python's input() returns a string, so to perform numeric operations you must cast the input to an integer. The lecturer demonstrated this by converting the typed value 5 into an int before multiplying it by 5.",
   "terms": [
    "input()",
    "casting",
    "int"
   ],
   "background": null,
   "quote": "Whatever you type in, just by default, by definition of the Input command, python always makes it a string"
  }
 ],
 "info": null
}
```

Validation: `filler: 'The lecturer demonstrated this by converting the typed value'`; `term_dropped:'input()'`; `term_dropped:'casting'`; `term_dropped:'int'`


## Update 9: 13:30-15:00

openai/gpt-oss-20b, 0.86 s, 1296+227 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Comparison Operators",
   "text": "Comparison operators produce Boolean values, returning true or false when applied to compatible types. They work on ints, floats, and strings, but not between a string and a number. The double equal sign checks equality of values, while the single equal sign assigns a value to a variable.",
   "terms": [
    "comparison operators",
    "Boolean"
   ],
   "background": null,
   "quote": "So this is where comparison operators come in."
  },
  {
   "kind": "para",
   "lead": "Equality vs Assignment",
   "text": "The single equal sign assigns a value to a variable; the double equal sign tests whether two values are equal, yielding a Boolean result.",
   "terms": [
    "assignment",
    "equality"
   ],
   "background": null,
   "quote": "The single equal sign is an assignment. So you're taking a value and you're signing it to a variable. But when you're doing. Doing the double equal sign, this is the test for equality."
  }
 ],
 "info": null
}
```

Validation: `term_dropped:'comparison operators'`; `term_dropped:'Boolean'`; `term_dropped:'assignment'`; `term_dropped:'equality'`


## Update 10: 15:00-16:30

openai/gpt-oss-120b, 1.113 s, 1331+259 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Inequality and NOT",
   "text": "The != operator tests whether two values are not equal, returning true when they differ and false otherwise. The keyword not inverts a Boolean value, so not a yields false when a is true and true when a is false.",
   "terms": [
    "!= operator",
    "not"
   ],
   "background": null,
   "quote": "is the value of the variable i not equal to the value of the variable j, true if yes, false if no"
  },
  "kind",
  ":",
  "para",
  "lead",
  ":",
  "Logical AND",
  "/OR Table\",\"text\":\"A and B evaluates to true only when both operands are true; otherwise it is false. A or B evaluates to false only when both operands are false; otherwise it is true.\",\"terms\":[\"and\",\"or\"],\"background\":null,\"quote\":\"A and B is only true if both A and B are true. And A or B is only false if A and B are\"}],\"info\":null"
 ]
}
```

Validation: `term_dropped:'!= operator'`; `term_dropped:'not'`


## Update 11: 16:30-18:00

openai/gpt-oss-20b, 0.792 s, 1427+236 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "String Comparison",
   "text": "String comparison uses the same operators as numbers; for example, a > b returns true if a comes later in the alphabet than b. The comparison is lexicographic, so 'b' > 'a' is true and 'a' > 'b' is false. This allows tests such as checking whether one string alphabetically precedes another.",
   "terms": [
    "lexicographic"
   ],
   "background": null,
   "quote": "So b becomes later in the alphabet than a"
  },
  {
   "kind": "para",
   "lead": "Branching Motivation",
   "text": "Branching lets a program choose between different actions based on test results. The lecturer illustrated this with a maze example: by following a rule like keeping a right hand on a wall, one can navigate to a target such as free food. This demonstrates how conditional logic can guide algorithmic decisions.",
   "terms": [
    "branching"
   ],
   "background": null,
   "quote": "So we can add. Subranching to our programming toolbox"
  }
 ],
 "info": null
}
```

Validation: `sentence_unsupported(0.27): 'String comparison uses the same operators as numbers; for example, a >'`; `sentence_unsupported(0.25): "The comparison is lexicographic, so 'b' > 'a' is true and 'a' > 'b' is"`; `cascade: 'This allows tests such as checking whether one string alphab'`; `paragraph_dropped(0/3)`; `sentence_unsupported(0.22): 'Branching lets a program choose between different actions based on tes'`; `filler: 'The lecturer illustrated this with a maze example: by follow'`; `cascade: 'This demonstrates how conditional logic can guide algorithmi'`; `paragraph_dropped(0/2)`


## Consolidation 12:00-18:00 (open) -> cut at 18:00, llm

openai/gpt-oss-20b, 1.837 s, 2602+982 tokens

```json
{
 "topics": [
  {
   "n": 4,
   "title": "Casting Input to Numbers",
   "starts_at": "12:00"
  },
  {
   "n": 5,
   "title": "Comparison Operators and Booleans",
   "starts_at": "13:20"
  },
  {
   "n": 6,
   "title": "Logical Operators and Branching",
   "starts_at": "15:30"
  }
 ],
 "elements": [
  {
   "topic": 4,
   "kind": "para",
   "lead": "Casting Input",
   "text": "Python's input() returns a string by default. To perform numeric operations, the input must be cast to an integer or float. The lecturer demonstrated this by converting a user‑entered value before multiplying it by 5.",
   "terms": [
    "input()",
    "casting",
    "integer"
   ],
   "quote": "Python always…by default, by definition of the Input command, python always makes it a string."
  },
  {
   "topic": 4,
   "kind": "example",
   "title": "Multiplying User Input",
   "text": "The code multiplies the cast integer by 5 and prints the result.",
   "steps": [
    "user_input = input(\"Enter a number: \")",
    "number = int(user_input)",
    "print(number * 5)"
   ],
   "quote": "user gives me 5, I'm going to print out 5 times 5 instead of 5 times."
  },
  {
   "topic": 5,
   "kind": "para",
   "lead": "Comparison Operators",
   "text": "Comparison operators produce Boolean values. They work on ints, floats, and strings, but not between a string and a number. The lecturer showed an error when comparing a string to a number.",
   "terms": [
    "comparison operators",
    "Boolean"
   ],
   "quote": "you are allowed to compare ints with ints, floats with floats, strings with strings. And you're allowed to compare ints and floats between themselves, but you're not allowed to compare a string with a number."
  },
  {
   "topic": 5,
   "kind": "example",
   "title": "Invalid Comparison",
   "text": "Attempting to compare a string to a number raises a TypeError.",
   "code": "print('A' > 5)",
   "quote": "if you even try to do that in Python, in Spider here, if I try to say, is the letter A greater than 5?"
  },
  {
   "topic": 5,
   "kind": "para",
   "lead": "Equality vs Assignment",
   "text": "The single equal sign assigns a value to a variable. The double equal sign tests equality, yielding a Boolean. The lecturer emphasized that equality checks the value, not the variable name.",
   "terms": [
    "assignment",
    "equality"
   ],
   "quote": "the single equal sign is an assignment. So you're taking a value and you're signing it to a variable. But when you're doing. Doing the double equal sign, this is the test for equality."
  },
  {
   "topic": 5,
   "kind": "para",
   "lead": "Inequality and NOT",
   "text": "The != operator tests for inequality, returning true when values differ. The keyword not inverts a Boolean value; not a is false if a is true.",
   "terms": [
    "inequality",
    "not"
   ],
   "quote": "you can also test for inequality with the exclamation equal. So that means, is the value of the variable i not equal to the value of the variable j, true if yes, false if no."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Logical Operators",
   "text": "Logical operators and, or, and not operate on Boolean values. A and B is true only if both are true; A or B is false only if both are false.",
   "terms": [
    "and",
    "or",
    "not"
   ],
   "quote": "A and B is only true if both A and B are true. And A or B is only false if A and B are."
  },
  {
   "topic": 6,
   "kind": "table",
   "caption": "Truth Table for and/or",
   "columns": [
    "A",
    "B",
    "A and B",
    "A or B"
   ],
   "rows": [
    [
     "True",
     "True",
     "True",
     "True"
    ],
    [
     "True",
     "False",
     "False",
     "True"
    ],
    [
     "False",
     "True",
     "False",
     "True"
    ],
    [
     "False",
     "False",
     "False",
     "False"
    ]
   ],
   "quote": "This is the complete table, just in case you need to reference it."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Branching Motivation",
   "text": "The lecturer used a campus‑maze example to motivate branching. By keeping a right hand on a wall, one can navigate to free food. This illustrates conditional logic in practice.",
   "terms": [
    "branching"
   ],
   "quote": "I might not, there might not"
  }
 ],
 "questions": [
  {
   "topic": 4,
   "q": "Why must input be cast to a number before arithmetic?",
   "answer": "Because input() returns a string by default."
  },
  {
   "topic": 5,
   "q": "What happens if you compare a string to a number?",
   "answer": "Python raises a TypeError."
  },
  {
   "topic": 6,
   "q": "When is A or B false?",
   "answer": "Only when both A and B are false."
  }
 ],
 "in_progress_from": null
}
```

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-120b', 'local_budget')]

Validation: `filler: 'The lecturer demonstrated this by converting a user‑entered '`; `term_dropped:'input()'`; `term_dropped:'casting'`; `term_dropped:'integer'`; `quote_near_verbatim`; `filler: 'The lecturer showed an error when comparing a string to a nu'`; `term_dropped:'comparison operators'`; `term_dropped:'Boolean'`; `code_unsupported(0.00)`; `filler: 'The lecturer emphasized that equality checks the value, not '`; `term_dropped:'assignment'`; `term_dropped:'equality'`; `term_dropped:'inequality'`; `term_dropped:'not'`; `term_dropped:'and'`; `term_dropped:'or'`; `term_dropped:'not'`; `filler: 'The lecturer used a campus‑maze example to motivate branchin'`; `sentence_unsupported(0.00): 'This illustrates conditional logic in practice.'`; `term_dropped:'branching'`; `short_topic_merged:'Casting Input to Numbers' -> 'Notes 06:00–12:00' (2 kept, 0 repeated)`


## Update 12: 18:00-19:30

Validation: `llm_failed:all_failed [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-20b', 'local_budget')]`


## Update 13: 19:30-20:00

openai/gpt-oss-20b, 0.812 s, 1153+182 tokens

```json
{
 "elements": [
  {
   "kind": "para",
   "lead": "Decision Point",
   "text": "A decision point is where the program must choose between two or more paths. The computer evaluates a condition and then executes the branch that satisfies it. This is the core of control flow in programming.",
   "terms": [
    "decision point",
    "control flow",
    "if"
   ],
   "background": null,
   "quote": "the decision point and say, OK, this is a decision point"
  },
  {
   "kind": "para",
   "lead": "If Statement",
   "text": "The simplest control structure is the if statement, which makes one decision and executes one block of code or another based on a Boolean condition.",
   "terms": [
    "if statement"
   ],
   "background": null,
   "quote": "the first is the simple if"
  }
 ],
 "info": null
}
```

Validation: `sentence_unsupported(0.33): 'The computer evaluates a condition and then executes the branch that s'`; `cascade: 'This is the core of control flow in programming.'`; `paragraph_dropped(1/3)`; `sentence_unsupported(0.36): 'The simplest control structure is the if statement, which makes one de'`; `paragraph_dropped(0/1)`


## Consolidation 18:00-20:00 (closed) -> cut at 20:00, llm

openai/gpt-oss-20b, 1.287 s, 1713+506 tokens

```json
{
 "topics": [
  {
   "n": 6,
   "title": "Control Flow with If Statements",
   "starts_at": "18:00"
  }
 ],
 "elements": [
  {
   "topic": 6,
   "kind": "para",
   "lead": "If Statements",
   "text": "The algorithm follows a simple rule: if there is a wall to the right and the path forward is clear, keep moving forward. If a wall appears to the right and also in front, turn around and go left. If walls surround the right, front, and left, turn around and go back.",
   "terms": [
    "If statement"
   ],
   "quote": "If there's a wall to my right and I can go forward, I'm just going to keep going forward, okay?"
  },
  {
   "topic": 6,
   "kind": "example",
   "title": "Wall‑Following Robot",
   "text": "The robot keeps the wall on its right side, turning only when obstacles block its path.",
   "steps": [
    "Check right wall",
    "Check front wall",
    "Decide turn or go forward"
   ],
   "quote": "I just follow the path, always keeping the wall to my right, and eventually I end up where I need to be."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Programming Constructs",
   "text": "In programming, the same keywords—if, otherwise—are used to instruct the computer to make decisions. These constructs let the program choose between different actions based on conditions.",
   "terms": [
    "if",
    "otherwise"
   ],
   "quote": "So in programming, we have those same We'll see you in the next one."
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Decision Points",
   "text": "The computer reads a decision point and selects a path: left or right, or another option. The programmer defines the logic; the computer merely executes it.",
   "terms": [
    "decision point"
   ],
   "quote": "Should I go left or should I go right? Or which one do I pick?"
  },
  {
   "topic": 6,
   "kind": "para",
   "lead": "Control Flow Types",
   "text": "There are three simple ways to add control flow: making one decision, choosing between two actions, or selecting among multiple possibilities.",
   "terms": [
    "control flow"
   ],
   "quote": "And the computer just has to make the decision and choose a path."
  }
 ],
 "questions": [
  {
   "topic": 6,
   "q": "What does the robot do when a wall is detected both to its right and in front?",
   "answer": "It turns around and goes left."
  }
 ]
}
```

Attempts that failed first: [('openai/gpt-oss-120b', 'HTTP 429'), ('openai/gpt-oss-120b', 'local_budget')]

Validation: `repeat: 'If walls surround the right, front, and left, turn around an'`; `term_dropped:'If statement'`; `term_dropped:'if'`; `term_dropped:'otherwise'`; `term_dropped:'decision point'`; `term_dropped:'control flow'`
