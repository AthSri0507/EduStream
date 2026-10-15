# Step-0 prototype: notebook prompt on Python · Lecture 1 (first 12 min, real Whisper output)


## Update 0: 00:00-01:30

<details><summary>Transcript sent</summary>

```
[00:00] The following content is provided under a Creative Commons license. Your support will help MIT OpenCourseWare continue to offer high quality educational resources.
[00:10] for free. To make a donation or view additional materials from hundreds of MIT courses, visit MIT OpenCourseWare at ocw.mit.
[00:20] .edu.
[00:30] Alright, let's begin. So, as I mentioned before, this lecture will be recorded for OCW. So, again, in future lectures, if you don't want to.
[00:40] to have the back of your head show up, just don't sit in this front area here. So first of all, wow, what a crowd you guys. We're finally in 26, 100, six triple one, made it.
[00:50] Big, huh? So good afternoon and welcome to the very first class of 6.001 And also 600 this semester so my name is Anna Bell
[01:00] first name Anna, last name Belle. I'm a lecturer in the EECS department and I'll be giving some of the lectures for today along with
[01:10] Later on in the term, Professor Eric Grimson, who's sitting right down there, will be giving some of the lectures as well. Okay, so today we're going to go over some
[01:20] just basic administrative, a little bit of course information. And then we're going to talk a little bit about what is computation. So we'll discuss at a very high level what computers do, just to make sure we're all on the same.
```
</details>

**LLM** (openai/gpt-oss-120b, 0.83 s, 871+125 tokens): section `new` Introduction & Course Overview; points kept 0/0

```json
{
 "section": {
  "action": "new",
  "title": "Introduction & Course Overview",
  "starts_at": "00:00"
 },
 "points": [],
 "terms": [
  {
   "term": "computation",
   "definition": "the process of performing logical or mathematical operations using a computer or algorithmic procedure",
   "t": "01:20",
   "quote": "what is computation",
   "source": "background"
  }
 ]
}
```

Validation flags: `premature_new_section_ignored:'Introduction & Course Overview'`


## Update 1: 01:30-03:00

<details><summary>Transcript sent</summary>

```
[01:30] Same page. And then we're going to dive right into Python basics. We're going to talk a little bit about mathematical operations. You can do with python. And then we're going to talk about python
[01:40] Types. So as i mentioned in my introductory email, all the slides in code that i'll talk about during lectures will be up before lecture. So i highly encourage you to download them.
[01:50] And to have them open, we're going to go through Something class exercises, which will be available on the slides. And it's fun to do.
[02:00] It's also great if you could take notes on the code just for future reference. It's true.
[02:10] This is a really fast-paced course and we ramp up really quickly so we do want to position you to succeed in this course So as I was writing this I was trying to think about
[02:20] When I was first starting the program, you know what helped me get through my first, very first programming course. And this is really like a good list. So the first thing was...
[02:30] was I just read the P sets as soon as they came out, made sure that the terminology kind of just sunk in. And then during lectures, if the lecturer was talking.
[02:40] talking about something that, you know, suddenly I remembered, oh I saw that word in the p-set and I didn't know what it was, well hey now I know what it is, right. So just give it a read, you don't need to start it.
[02:50] If you're new to programming, I think the keyword is practice, so it's like math or reading. The more you practice, the better you get at it.
```
</details>

**LLM** (openai/gpt-oss-120b, 1.28 s, 929+364 tokens): section `continue` ; points kept 3/3

```json
{
 "section": {
  "action": "continue"
 },
 "points": [
  {
   "text": "Python basics cover syntax, variables, and simple statements needed to write runnable code.",
   "t": "01:30",
   "kind": "point",
   "quote": "Same page. And then we're going to dive right into Python basics."
  },
  {
   "text": "Mathematical operations in Python include addition (+), subtraction (-), multiplication (*), division (/), and exponentiation (**).",
   "t": "01:30",
   "kind": "point",
   "quote": "We're going to talk a little bit about mathematical operations. You can do with python."
  },
  {
   "text": "Python has built‑in data types such as integers, floats, strings, lists, and dictionaries; understanding them is essential early on.",
   "t": "01:50",
   "kind": "point",
   "quote": "And to have them open, we're going to go through Something class exercises"
  }
 ],
 "terms": [
  {
   "term": "Python basics",
   "definition": "Fundamental concepts of Python language: syntax, variables, control flow, and simple I/O.",
   "t": "01:30",
   "quote": "... dive right into Python basics",
   "source": "lecture"
  },
  {
   "term": "mathematical operations",
   "definition": "Operators that perform arithmetic on numeric types, e.g., +, -, *, /, **.",
   "t": "01:30",
   "quote": "... talk a little bit about mathematical operations",
   "source": "lecture"
  },
  {
   "term": "Types",
   "definition": "Categories of data values (int, float, str, list, dict) that determine allowed operations.",
   "t": "01:50",
   "quote": "... talk about python Types",
   "source": "lecture"
  }
 ]
}
```


## Update 2: 03:00-04:30

<details><summary>Transcript sent</summary>

```
[03:00] You're not going to absorb programming, but watching me write programs, because i already know how to program, right? You guys need to practice. So download the code before lecture, follow along.
[03:10] whatever I type. You guys can type. And I think also one of the Big things is if you're new to programming, you're kind of Afraid that you're going to break your computer. Right? And you can't
[03:20] Really do that just by running anaconda and typing in some commands. So don't be afraid to just type some stuff in and see what it does.
[03:30] You just restart the computer. So, yeah. Yeah. So that's probably the big thing right there. I should probably highlight it. But don't be afraid.
[03:40] Great. So this is pretty much a road map of all of 6 Triple 1 or 600 as i've just explained it. So there's three big things we want you to get out of
[03:50] this course. The first thing is the knowledge of concepts, which is pretty much true of any class that you'll take, right? The class will teach you something through lectures, examples.
[04:00] will test how much you know. This is a class in programming, right? The other thing we need you, we want you to get out of it is programming skills.
[04:10] And the last thing, and I think this is what makes this class really great, is we teach you how to solve problems, and we do that through the p sets. So that's really how I feel the
[04:20] road map of this course looks like. And underlying all of these is just practice. So you have to just type some stuff away and code a lot.
```
</details>

**LLM** (openai/gpt-oss-120b, 1.29 s, 1023+329 tokens): section `continue` ; points kept 3/3

```json
{
 "section": {
  "action": "continue"
 },
 "points": [
  {
   "text": "Practice is essential: repeatedly typing code and observing results builds programming ability.",
   "t": "03:20",
   "kind": "point",
   "quote": "Really do that just by running anaconda and typing in some commands."
  },
  {
   "text": "The course aims for three outcomes: conceptual knowledge, programming skills, and problem‑solving ability via problem sets.",
   "t": "04:00",
   "kind": "point",
   "quote": "The other thing we need you, we want you to get out of it is programming skills."
  },
  {
   "text": "Don't fear breaking your computer; you can always restart and try again.",
   "t": "03:30",
   "kind": "point",
   "quote": "You just restart the computer."
  }
 ],
 "terms": [
  {
   "term": "programming skills",
   "definition": "Practical ability to write, run, and debug code, developed through hands‑on coding exercises.",
   "t": "04:00",
   "quote": "The other thing we need you, we want you to get out of it is programming skills.",
   "source": "lecture"
  },
  {
   "term": "problem solving",
   "definition": "Applying programming techniques to tackle defined tasks, reinforced by regular problem‑set assignments.",
   "t": "04:10",
   "quote": "we teach you how to solve problems, and we do that through the p sets.",
   "source": "lecture"
  }
 ]
}
```

Validation flags: `dropped_term_not_in_transcript:'problem solving'`


## Update 3: 04:30-06:00

<details><summary>Transcript sent</summary>

```
[04:30] And you'll succeed in this course, I think. Okay. So what are the things we're going to learn in this class? I feel like.
[04:40] The things we're going to learn in this class can be divided into basically three different sections. So the first one is related to these first two items here.
[04:50] So it's really about learning how to program. So learning how to program is, part of it is figuring out what objects to create. You'll learn about these. . . . . . . .
[05:00] How do you represent knowledge with data structures? That's sort of the broad term for that. And then as you're writing programs, you need to, programs Aren't just linear. Sometimes programs jump
[05:10] They make decisions, there's some control flow to programs. So that's what the second line is going to be about. The second big part of this course.
[05:20] This is a little bit more abstract, and it deals with how do you write good code, good style. code that's readable.
[05:30] So, when you write code, you want to write it such that, you know, you're in a big company, other people will read it, other people will use it, so it has to be readable and understandable by others.
[05:40] So to that end, you need to write code that's well-organized, modular, easy to understand, right? And not only that, not only.
[05:50] will your code be read by other people? But next year, maybe you'll take another course and you'll want to look back at some of the problem sets you wrote in this class. You kind of want to be able to reread your.
```
</details>

**LLM** (openai/gpt-oss-120b, 1.87 s, 1085+506 tokens): section `continue` ; points kept 3/3

```json
{
 "section": {
  "action": "continue"
 },
 "points": [
  {
   "text": "The course material splits into three main parts: basic programming, control‑flow concepts, and writing clean, readable code.",
   "t": "04:40",
   "kind": "point",
   "quote": "The things we're going to learn in this class can be divided into basically three different sections."
  },
  {
   "text": "Control flow refers to the ways a program can branch or loop, allowing decisions rather than just linear execution.",
   "t": "05:10",
   "kind": "point",
   "quote": "They make decisions, there's some control flow to programs."
  },
  {
   "text": "Good code style means writing code that is well‑organized, modular, and easy for others (or your future self) to understand.",
   "t": "05:40",
   "kind": "point",
   "quote": "you need to write code that's well-organized, modular, easy to understand"
  }
 ],
 "terms": [
  {
   "term": "control flow",
   "definition": "The mechanisms (e.g., if‑else, loops) that let a program change its execution path based on conditions.",
   "t": "05:10",
   "quote": "They make decisions, there's some control flow to programs.",
   "source": "lecture"
  },
  {
   "term": "modular",
   "definition": "Dividing a program into separate, self‑contained components or functions that can be developed and understood independently.",
   "t": "05:40",
   "quote": "you need to write code that's well-organized, modular, easy to understand",
   "source": "lecture"
  }
 ]
}
```


## Update 4: 06:00-07:30

<details><summary>Transcript sent</summary>

```
[06:00] code, right? If it's a big mess, you might not be able to understand or re-understand what you were doing. So writing readable code and organizing code is also a big part.
[06:10] And the last section is going to deal with, so the first two are actually part of the programming in Introduction to Programming and Computing.
[06:20] science in Python. And the last one deals mostly with the computer science part in introduction to programming and computer science in Python. So we're going to talk
[06:30] Once you've learned how to write programs in python, how do you compare programs in python? How do you know that one program is better than the other? How do you know that one program is more efficient?
[06:40] how do you know that one algorithm is better than the other? So that's where we're going to talk about in the last part of the course. Okay.
[06:50] So that's all for the sort of administrative part of the course. So let's start by talking at a high level what does a computer do. So, fundamental...
[07:00] Mentally, it does two things. One, performs calculations. And it performs a lot of calculations, right? Computers these days are really, really fast. A billion.
[07:10] calculations per second is probably not far off. It performs these calculations and it has to store them somewhere, right? Store them in computer memory.
[07:20] So a computer also has to remember results. And these days it's not uncommon to find computers with hundreds of gigabytes of storage.
```
</details>

**LLM** (openai/gpt-oss-20b, 0.85 s, 1068+412 tokens): section `continue` Introduction & Course Overview; points kept 3/4

```json
{
 "section": {
  "action": "continue",
  "title": "Introduction & Course Overview"
 },
 "points": [
  {
   "text": "Readable code is essential; messy code hinders understanding and future debugging.",
   "t": "06:00",
   "kind": "point",
   "quote": "code, right? If it's a big mess, you might not be able to understand or re-understand what you were doing."
  },
  {
   "text": "Course structure: basic programming, control‑flow, and clean code; last part focuses on computer science concepts in Python.",
   "t": "06:10",
   "kind": "point",
   "quote": "And the last section is going to deal with, so the first two are actually part of the programming in Introduction to Programming and Computing."
  },
  {
   "text": "Evaluation criteria: program quality measured by readability, efficiency, and algorithmic performance.",
   "t": "06:30",
   "kind": "point",
   "quote": "Once you've learned how to write programs in python, how do you compare programs in python? How do you know that one program is better than the other?"
  },
  {
   "text": "Computers perform ~1 billion calculations per second and store results in memory; modern systems have hundreds of GB storage.",
   "t": "07:00",
   "kind": "point",
   "quote": "A billion. calculations per second is probably not far off. It performs these calculations and it has to store them somewhere, right?"
  }
 ],
 "terms": [
  {
   "term": "algorithmic performance",
   "definition": "How well an algorithm uses time and space resources compared to alternatives.",
   "t": "06:30",
   "quote": "how do you know that one algorithm is better than the other?",
   "source": "lecture"
  },
  {
   "term": "computer memory",
   "definition": "Hardware that temporarily holds data and program instructions during execution.",
   "t": "07:10",
   "quote": "It performs these calculations and it has to store them somewhere, right? Store them in computer memory.",
   "source": "lecture"
  }
 ]
}
```

Validation flags: `dropped_low_overlap(0.11):'Evaluation criteria: program quality measured by r'`; `dropped_term_not_in_transcript:'algorithmic performance'`


## Update 5: 07:30-09:00

<details><summary>Transcript sent</summary>

```
[07:30] So the kinds of calculations that computers do, there are two kinds. So one are calculations that are built into the language. So these are the very low level types of calculations.
[07:40] things like addition, subtraction, multiplication, and so on. And once you have a language that has these sort of primitive
[07:50] Calculation types, you as a programmer can put these types Together and then define your own calculations. Okay, and you create nuke times types of calculations.
[08:00] And the computer will be able to perform those as well. And I think one thing I want to stress, and we're going to come back to this again.
[08:10] And again, during this entire lecture actually is computers only know what you tell them.
[08:20] don't have a mind. They just know how to perform calculations really, really quickly. But you have to tell them what calculations to do.
[08:30] Okay, computers don't know anything, all right, we've come to that, so...
[08:40] Let's go into the types of knowledge. The first type of knowledge is declarative knowledge. And those are things like statements of fact.
[08:50] OK, and this is where my email came into play. If you read it all the way to the bottom, you would have entered a raffle. OK, so statement of fact for today's lecture is.
```
</details>

**LLM** (openai/gpt-oss-20b, 0.96 s, 1043+348 tokens): section `new` Types of Calculations & Knowledge; points kept 4/4

```json
{
 "section": {
  "action": "new",
  "title": "Types of Calculations & Knowledge",
  "starts_at": "07:30"
 },
 "points": [
  {
   "text": "Computers perform two kinds of calculations: built‑in primitive operations (add, subtract, multiply) and user‑defined calculations built from these primitives.",
   "t": "07:30",
   "kind": "point",
   "quote": "So the kinds of calculations that computers do, there are two kinds. So one are calculations that are built into the language."
  },
  {
   "text": "Programmers can combine primitive types to create new calculations; the computer then executes them just like built‑in ones.",
   "t": "07:50",
   "kind": "point",
   "quote": "you as a programmer can put these types Together and then define your own calculations."
  },
  {
   "text": "Computers only know what they are told; they lack independent reasoning and perform calculations only when instructed.",
   "t": "08:10",
   "kind": "point",
   "quote": "computers only know what you tell them."
  },
  {
   "text": "First type of knowledge: declarative knowledge—statements of fact that the computer can store and retrieve.",
   "t": "08:40",
   "kind": "point",
   "quote": "The first type of knowledge is declarative knowledge. And those are things like statements of fact."
  }
 ],
 "terms": [
  {
   "term": "Declarative knowledge",
   "definition": "Statements of fact that can be stored and queried by a computer.",
   "t": "08:40",
   "quote": "The first type of knowledge is declarative knowledge. And those are things like statements of fact.",
   "source": "lecture"
  }
 ]
}
```


## Update 6: 09:00-10:30

<details><summary>Transcript sent</summary>

```
[09:00] Someone will win a prize before class ends. And the prize was a Google Cardboard, right? Google State of the Art, Virtual Reality Glasses.
[09:10] I have the right here, yay. Okay, I delivered on my promise, okay. So that's a statement of fact, but.
[09:20] But if you pretend I'm a machine, okay, I don't know anything except what you tell me, what you tell me. So I don't know, I know that you tell me the statement.
[09:30] And I'm like, OK. But how is someone going to win a Google Cardboard before class ends? That's where imperative knowledge comes in. So imperative knowledge is the recipe, or the how-to, or the sequence.
[09:40] of steps. Sorry. That's just my funny for that one. So the sequence of steps.
[09:50] is the imperative knowledge. So if I'm a machine, you need to tell me how someone will win a Google Cardboard before class.
[10:00] So if I follow these steps, then technically I should reach a conclusion. Okay. So step one, I think we've already done that. Whoever wanted to sign up.
[10:10] had signed up. So now I'm going to open my IDE. So I'm just basically being a machine and following the steps that you've told me. So the IDE that we're using in this class is called
[10:20] anaconda. I'm just go down to the bottom. Okay, hopefully you've installed it in problem set zero. So I've opened my IDE.
```
</details>

**LLM** (openai/gpt-oss-20b, 0.8 s, 1042+260 tokens): section `continue` ; points kept 3/3

```json
{
 "section": {
  "action": "continue"
 },
 "points": [
  {
   "text": "Imperative knowledge = recipe or sequence of steps a machine follows to achieve a goal.",
   "t": "09:30",
   "kind": "point",
   "quote": "imperative knowledge is the recipe, or the how-to, or the sequence"
  },
  {
   "text": "Example: to win a Google Cardboard before class, machine must execute steps: sign up, open IDE, etc.",
   "t": "10:00",
   "kind": "example",
   "quote": "So if I follow these steps, then technically I should reach a conclusion"
  },
  {
   "text": "IDE used in class is Anaconda, which must be installed before problem set zero.",
   "t": "10:20",
   "kind": "point",
   "quote": "the IDE that we're using in this class is called anaconda"
  }
 ],
 "terms": [
  {
   "term": "imperative knowledge",
   "definition": "A type of knowledge that specifies a sequence of actions or steps a machine must follow to achieve a goal.",
   "t": "09:30",
   "quote": "imperative knowledge is the recipe, or the how-to, or the sequence",
   "source": "lecture"
  }
 ]
}
```


## Update 7: 10:30-12:00

<details><summary>Transcript sent</summary>

```
[10:30] I'm going to follow the next set of instructions. I'm going to choose a random number between the first and the end responder. Now, I'm gonna...
[10:40] actually use Python to do this. And this is also an example of how just like a really simple task in your life. You can use computers or programming to do that. Because if I chose a random number.
[10:50] I might be biased because, for example, I might like the number eight. So to choose a random number, I'm going to go and say, okay, where's the list of responders? It starts at 15. Actually.
[11:00] It starts at 16 because that's me, okay. So we're going to choose a random number between 16 and the end person 266. up we just
[11:10] I'm going to cut it off right here at 271. 16 and 271. Perfect. Okay.
[11:20] So, I'm going to choose a random number, so I'm going to go to my ID, and you don't need to know how to do this yet, but by the end of this class you will, so I'm just going to use Python. I'm just going to get...
[11:30] the random number package that's going to get me a random number. So I'm going to say random dot rand int. And I'm going to choose a random number between 16 and 272.
[11:40] Okay. 75. Okay. Great. So I chose a random number and I'm going to find the number in the responder's sheet. What was the number again? Sorry.
[11:50] 75. Okay. Up we go. There we go. Lauren, ZOV.
```
</details>

**LLM** (openai/gpt-oss-20b, 0.78 s, 1118+247 tokens): section `continue` ; points kept 3/3

```json
{
 "section": {
  "action": "continue"
 },
 "points": [
  {
   "text": "Use Python's random module to generate a random integer: random.randint(16,272).",
   "t": "11:30",
   "kind": "example",
   "quote": "random dot rand int"
  },
  {
   "text": "Demonstrates imperative knowledge: a step‑by‑step recipe for selecting a random number and locating it in a list.",
   "t": "11:20",
   "kind": "point",
   "quote": "I'm going to choose a random number, so I'm going to go to my ID, and you don't need to know how to do this yet, but by the end of this class you will"
  },
  {
   "text": "Shows bias in random selection: the speaker admits a preference for the number eight, illustrating human influence on supposedly random processes.",
   "t": "10:40",
   "kind": "point",
   "quote": "I might be biased because, for example, I might like the number eight"
  }
 ],
 "terms": [
  {
   "term": "random.randint",
   "definition": "Python function that returns a random integer N such that a <= N <= b.",
   "t": "11:30",
   "quote": "random dot rand int",
   "source": "lecture"
  }
 ]
}
```

Validation flags: `dropped_term_not_in_transcript:'random.randint'`


---

# Resulting notebook (LLM, after validation)

### 1. Introduction & Course Overview
- `[01:30]` Python basics cover syntax, variables, and simple statements needed to write runnable code.  
  <sub>quote: "Same page. And then we're going to dive right into Python basics."</sub>
- `[01:30]` Mathematical operations in Python include addition (+), subtraction (-), multiplication (*), division (/), and exponentiation (**).  
  <sub>quote: "We're going to talk a little bit about mathematical operations. You can do with python."</sub>
- `[01:50]` Python has built‑in data types such as integers, floats, strings, lists, and dictionaries; understanding them is essential early on.  
  <sub>quote: "And to have them open, we're going to go through Something class exercises"</sub>
- `[03:20]` Practice is essential: repeatedly typing code and observing results builds programming ability.  
  <sub>quote: "Really do that just by running anaconda and typing in some commands."</sub>
- `[04:00]` The course aims for three outcomes: conceptual knowledge, programming skills, and problem‑solving ability via problem sets.  
  <sub>quote: "The other thing we need you, we want you to get out of it is programming skills."</sub>
- `[03:30]` Don't fear breaking your computer; you can always restart and try again.  
  <sub>quote: "You just restart the computer."</sub>
- `[04:40]` The course material splits into three main parts: basic programming, control‑flow concepts, and writing clean, readable code.  
  <sub>quote: "The things we're going to learn in this class can be divided into basically three different sections."</sub>
- `[05:10]` Control flow refers to the ways a program can branch or loop, allowing decisions rather than just linear execution.  
  <sub>quote: "They make decisions, there's some control flow to programs."</sub>
- `[05:40]` Good code style means writing code that is well‑organized, modular, and easy for others (or your future self) to understand.  
  <sub>quote: "you need to write code that's well-organized, modular, easy to understand"</sub>
- `[06:00]` Readable code is essential; messy code hinders understanding and future debugging.  
  <sub>quote: "code, right? If it's a big mess, you might not be able to understand or re-understand what you were doing."</sub>
- `[06:10]` Course structure: basic programming, control‑flow, and clean code; last part focuses on computer science concepts in Python.  
  <sub>quote: "And the last section is going to deal with, so the first two are actually part of the programming in Introduction to Programming and Computing."</sub>
- `[07:00]` Computers perform ~1 billion calculations per second and store results in memory; modern systems have hundreds of GB storage.  
  <sub>quote: "A billion. calculations per second is probably not far off. It performs these calculations and it has to store them somewhere, right?"</sub>
### 2. Types of Calculations & Knowledge
- `[07:30]` Computers perform two kinds of calculations: built‑in primitive operations (add, subtract, multiply) and user‑defined calculations built from these primitives.  
  <sub>quote: "So the kinds of calculations that computers do, there are two kinds. So one are calculations that are built into the language."</sub>
- `[07:50]` Programmers can combine primitive types to create new calculations; the computer then executes them just like built‑in ones.  
  <sub>quote: "you as a programmer can put these types Together and then define your own calculations."</sub>
- `[08:10]` Computers only know what they are told; they lack independent reasoning and perform calculations only when instructed.  
  <sub>quote: "computers only know what you tell them."</sub>
- `[08:40]` First type of knowledge: declarative knowledge—statements of fact that the computer can store and retrieve.  
  <sub>quote: "The first type of knowledge is declarative knowledge. And those are things like statements of fact."</sub>
- `[09:30]` Imperative knowledge = recipe or sequence of steps a machine follows to achieve a goal.  
  <sub>quote: "imperative knowledge is the recipe, or the how-to, or the sequence"</sub>
- `[10:00]` *Example:* Example: to win a Google Cardboard before class, machine must execute steps: sign up, open IDE, etc.  
  <sub>quote: "So if I follow these steps, then technically I should reach a conclusion"</sub>
- `[10:10]` IDE used in class is Anaconda, which must be installed before problem set zero.  
  <sub>quote: "the IDE that we're using in this class is called anaconda"</sub>
- `[11:30]` *Example:* Use Python's random module to generate a random integer: random.randint(16,272).  
  <sub>quote: "random dot rand int"</sub>
- `[11:20]` Demonstrates imperative knowledge: a step‑by‑step recipe for selecting a random number and locating it in a list.  
  <sub>quote: "I'm going to choose a random number, so I'm going to go to my ID, and you don't need to know how to do this yet, but by the end of this class you will"</sub>
- `[10:50]` Shows bias in random selection: the speaker admits a preference for the number eight, illustrating human influence on supposedly random processes.  
  <sub>quote: "I might be biased because, for example, I might like the number eight"</sub>

**Glossary:** **computation** *(background)*: the process of performing logical or mathematical operations using a computer or algorithmic procedure `[01:20]`; **Python basics**: Fundamental concepts of Python language: syntax, variables, control flow, and simple I/O. `[01:30]`; **mathematical operations**: Operators that perform arithmetic on numeric types, e.g., +, -, *, /, **. `[01:30]`; **Types**: Categories of data values (int, float, str, list, dict) that determine allowed operations. `[01:30]`; **programming skills**: Practical ability to write, run, and debug code, developed through hands‑on coding exercises. `[04:00]`; **control flow**: The mechanisms (e.g., if‑else, loops) that let a program change its execution path based on conditions. `[05:10]`; **modular**: Dividing a program into separate, self‑contained components or functions that can be developed and understood independently. `[05:40]`; **computer memory**: Hardware that temporarily holds data and program instructions during execution. `[07:10]`; **Declarative knowledge**: Statements of fact that can be stored and queried by a computer. `[08:40]`; **imperative knowledge**: A type of knowledge that specifies a sequence of actions or steps a machine must follow to achieve a goal. `[09:30]`


# Extractive fallback on the same updates

**00:00-01:30**
- `[00:40]` We're finally in 26, 100, six triple one, made it.
- `[00:50]` So good afternoon and welcome to the very first class of 6.001 And also 600 this semester so my name is Anna Bell
- `[01:00]` first name Anna, last name Belle.

**01:30-03:00**
- `[01:30]` We're going to talk a little bit about mathematical operations.
- `[02:20]` When I was first starting the program, you know what helped me get through my first, very first programming course.
- `[02:40]` talking about something that, you know, suddenly I remembered, oh I saw that word in the p-set and I didn't know what it was, well hey now I know what it is, right.

**03:00-04:30**
- `[03:00]` You're not going to absorb programming, but watching me write programs, because i already know how to program, right?
- `[03:10]` And I think also one of the Big things is if you're new to programming, you're kind of Afraid that you're going to break your computer.
- `[03:50]` The class will teach you something through lectures, examples.

**04:30-06:00**
- `[05:00]` And then as you're writing programs, you need to, programs Aren't just linear.
- `[05:30]` So, when you write code, you want to write it such that, you know, you're in a big company, other people will read it, other people will use it, so it has to be readable and understandable by others.
- `[05:50]` But next year, maybe you'll take another course and you'll want to look back at some of the problem sets you wrote in this class.

**06:00-07:30**
- `[06:10]` And the last section is going to deal with, so the first two are actually part of the programming in Introduction to Programming and Computing.
- `[06:20]` And the last one deals mostly with the computer science part in introduction to programming and computer science in Python.
- `[06:30]` Once you've learned how to write programs in python, how do you compare programs in python?

**07:30-09:00**
- `[07:30]` So these are the very low level types of calculations.
- `[07:50]` Calculation types, you as a programmer can put these types Together and then define your own calculations.
- `[07:50]` Okay, and you create nuke times types of calculations.

**09:00-10:30**
- `[09:00]` Someone will win a prize before class ends.
- `[09:30]` But how is someone going to win a Google Cardboard before class ends?
- `[09:50]` So if I'm a machine, you need to tell me how someone will win a Google Cardboard before class.

**10:30-12:00**
- `[10:40]` Because if I chose a random number.
- `[11:00]` So we're going to choose a random number between 16 and the end person 266.
- `[11:30]` the random number package that's going to get me a random number.