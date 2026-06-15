import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import time
import json
import re
import os
import tempfile
import aiohttp
import google.genai as genai
from google.genai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from google.genai import types
from config import system_prompt, gemini_api_key
import random
import asyncio
from beacon import beacon_commands, preconditions
from datetime import datetime, timezone
from pylatexenc.latex2text import LatexNodes2Text
import unicodeitplus
import mimetypes
from dataclasses import dataclass

client = genai.Client(api_key=gemini_api_key)

# PRODUCTION EMOJIS
#reportemoji = "<:ReportEmoji:1515283638164521031>"
#threedotemoji = "<:ThreedotEmoji:1515283624088436767>"
#retryemoji = "<:RetryEmoji:1515283585123483688>"
#backemoji = "<:BackEmoji:1515286702787395724>"
#twilightloading = "<a:twilight_loading_icon:1506347831605198981>"
#loadingdot = "<a:twilight_loading_dot:1506348237722878085>"

# TEST BENCH EMOJIS
reportemoji = "<:ReportEmoji:1516126283778756701>"
threedotemoji = "<:ThreedotEmoji:1516126288182644940>"
retryemoji = "<:RetryEmoji:1516126285775245352>"
backemoji = "<:BackEmoji:1516126262265909388>"
twilightloading = "<a:twilight_loading_icon:1516126476280398014>"
loadingdot = "<a:loadingdot:1516126281719218297>"

JUDGE_MODEL = "models/gemma-4-26b-a4b-it"
GENERALIST_MODEL = "models/gemma-4-26b-a4b-it"
EXPERT_MODEL = "models/gemma-4-26b-a4b-it"
SEARCH_MODEL = "models/gemma-4-31b-it"
MD_SEPARATOR = "𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖"
MEDIA_REGEX = re.compile(r'(https?://\S+)', re.IGNORECASE)
IMAGE_MEDIA_PATTERNS = [
    r"giphy\.com",
    r"tenor\.com",
    r"imgur\.com",
    r"pinimg\.com",
    r"media\.giphy\.com",
    r"i\.giphy\.com"
]

@dataclass
class ResponseMetadata:
    response_time_str: str
    model_name: str
    context_percent: str
    token_format: str
    timestamp: float
    thinking_process: str = ""


class ResponseCache:
    def __init__(self, ttl_seconds: int = 3600):
        self._cache = {}
        self.ttl = ttl_seconds

    def set(self, message_id: int, response_time: str, model: str, context: str, tokens: str, thinking_process: str = ""):
        self._cache[message_id] = ResponseMetadata(
            response_time_str=response_time,
            model_name=model,
            context_percent=context,
            token_format=tokens,
            timestamp=time.time(),
            thinking_process=thinking_process
        )
        self._cleanup()

    def get(self, message_id: int) -> ResponseMetadata | None:
        self._cleanup()
        return self._cache.get(message_id)

    def delete(self, message_id: int):
        if message_id in self._cache:
            del self._cache[message_id]

    def _cleanup(self):
        now = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if now - v.timestamp > self.ttl
        ]
        for k in expired_keys:
            del self._cache[k]


class MainResponseView(discord.ui.View):
    def __init__(self, cache, initial_time_str: str = "0.0s", timeout: float = 3600.0):
        super().__init__(timeout=timeout)
        self.cache = cache
        self.children[0].label = f" {initial_time_str} "

    @discord.ui.button(label="0.0s", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def response_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(retryemoji), row=0)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(threedotemoji), style=discord.ButtonStyle.secondary, row=0)
    async def overflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        overflow_view = OverflowButtonView(cache=self.cache)
        overflow_view.update_layout_from_cache(interaction.message.id)
        await interaction.response.edit_message(view=overflow_view)


class OverflowButtonView(discord.ui.View):
    def __init__(self, cache, timeout: float = 3600.0):
        super().__init__(timeout=timeout)
        self.cache = cache

    def update_layout_from_cache(self, message_id: int):
        metadata = self.cache.get(message_id)
        if metadata:
            self.children[0].label = f"Context: {metadata.context_percent}"
            self.children[1].label = f"Tokens: {metadata.token_format}"
            if not metadata.thinking_process:
                self.children[2].disabled = True

    @discord.ui.button(label="Context: --%", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def context_stat(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Tokens: --/--", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def token_stat(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Report Response", style=discord.ButtonStyle.danger, emoji=discord.PartialEmoji.from_str(reportemoji), row=1)
    async def report_response(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Response Flagged:** This generation has been reported for internal review.", ephemeral=True)

    @discord.ui.button(label="Show Thinking Process", style=discord.ButtonStyle.secondary,row=1)
    async def show_thinking(self, interaction: discord.Interaction, button: discord.ui.Button):
        metadata = self.cache.get(interaction.message.id)
        if metadata and metadata.thinking_process:
            await interaction.response.send_message(
                f"**Thinking Process:**\n```\n{metadata.thinking_process}\n```",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("No historical thinking process was recorded for this response.",
                                                    ephemeral=True)

    @discord.ui.button(label="Back", emoji=discord.PartialEmoji.from_str(backemoji), style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        metadata = self.cache.get(interaction.message.id)
        time_str = metadata.response_time_str if metadata else "0.0s"

        main_view = MainResponseView(cache=self.cache, initial_time_str=time_str)
        await interaction.response.edit_message(view=main_view)

class AICog(commands.Cog):
    _THINKING_STEP_RULES = [
        (["conclusion", "wrapping up", "final summary", "conclude", "closing remarks", "sign-off"],
         "Finalising Conclusion..."),
        (["body 3", "paragraph 3", "third paragraph", "final body"],
         "Developing Concluding Arguments..."),
        (["body 2", "paragraph 2", "second paragraph"],
         "Elaborating Core Points..."),
        (["body 1", "paragraph 1", "body paragraph", "first paragraph", "main argument"],
         "Formulating Core Arguments..."),
        (["thesis", "thesis statement", "central claim", "main thesis"],
         "Sharpening Thesis Statement..."),
        (["counterargument", "counter-argument", "rebuttal", "refutation", "opposing view"],
         "Addressing Counterarguments..."),
        (["transition", "topic sentence", "bridge sentence"],
         "Crafting Transitions..."),
        (["introduction", "introductory", "hook", "opening paragraph", "lead-in"],
         "Drafting Introduction..."),
        (["structure", "outline", "planning", "draft", "skeleton", "roadmap", "framework"],
         "Structuring Response..."),
        (["option 1", "option 2", "alternate", "variant", "alternative approach", "backup plan"],
         "Evaluating Response Variations..."),
        (["syntax", "bug", "error", "exception", "debug", "refactor", "stack trace", "crash", "segfault",
          "traceback", "breakpoint", "lint", "compiler error"],
         "Debugging & Refactoring Code..."),
        (["unit test", "integration test", "pytest", "jest", "mocha", "test case", "test suite", "mock",
          "coverage", "tdd", "assertion"],
         "Writing & Running Tests..."),
        (["code review", "pull request", "pr review", "nitpick", "review comment"],
         "Reviewing Code Changes..."),
        (["git", "commit", "branch", "merge", "rebase", "cherry-pick", "stash", "version control"],
         "Managing Version Control..."),
        (["docker", "container", "kubernetes", "k8s", "helm", "pod", "orchestrat"],
         "Configuring Containers & Orchestration..."),
        (["ci/cd", "pipeline", "github actions", "jenkins", "deploy", "deployment", "release",
          "terraform", "ansible", "infrastructure"],
         "Planning Build & Deployment..."),
        (["security", "vulnerability", "exploit", "xss", "csrf", "injection", "sanitize input",
          "penetration", "cve", "threat model"],
         "Assessing Security Risks..."),
        (["encrypt", "decrypt", "cipher", "cryptograph", "hash", "sha", "aes", "rsa", "signing",
          "certificate", "tls", "ssl handshake"],
         "Working Through Cryptography..."),
        (["oauth", "jwt", "authentication", "authorization", "login flow", "session", "permission",
          "rbac", "api key"],
         "Designing Auth & Permissions..."),
        (["algorithm", "complexity", "big o", "efficiency", "optimize", "performance", "runtime",
          "time complexity", "space complexity", "benchmark", "profil"],
         "Optimising Algorithmic Efficiency..."),
        (["edge case", "boundary condition", "null pointer", "validation", "sanitize", "corner case",
          "off-by-one", "race condition"],
         "Evaluating Edge Cases & Constraints..."),
        (["async", "await", "concurrent", "parallel", "thread", "mutex", "semaphore", "deadlock",
          "lock", "goroutine", "event loop"],
         "Reasoning About Concurrency..."),
        (["memory leak", "garbage collect", "allocation", "pointer", "buffer overflow", "heap", "stack frame"],
         "Analysing Memory & Resources..."),
        (["design pattern", "solid", "inheritance", "polymorphism", "encapsulation", "abstraction",
          "interface", "dependency injection", "singleton", "factory pattern"],
         "Applying Design Patterns..."),
        (["microservice", "monolith", "architecture", "scalab", "load balanc", "service mesh"],
         "Designing System Architecture..."),
        (["react", "vue", "angular", "svelte", "frontend", "dom", "component", "jsx", "css",
          "stylesheet", "responsive", "ui component"],
         "Building Frontend Components..."),
        (["backend", "server-side", "middleware", "route handler", "restful", "graphql", "grpc"],
         "Shaping Backend Logic..."),
        (["json", "xml", "csv", "regex", "parse", "schema", "format", "yaml", "toml", "protobuf",
          "serialization", "deserial"],
         "Structuring Data Formats..."),
        (["database", "sql", "query", "index", "nosql", "mongodb", "postgres", "mysql", "sqlite",
          "orm", "migration", "join table"],
         "Designing Database Queries..."),
        (["api", "endpoint", "http request", "api request", "request body", "payload", "webhook",
          "status code", "rest api", "graphql query"],
         "Mapping API Interactivity..."),
        (["network", "tcp", "udp", "socket", "dns", "ip address", "firewall", "proxy", "latency",
          "bandwidth", "packet"],
         "Tracing Network Behaviour..."),
        (["pip install", "npm install", "cargo", "package.json", "requirements.txt", "dependency",
          "lockfile", "virtualenv", "venv"],
         "Resolving Dependencies..."),
        (["function", "method", "class ", " variable", "loop", "recursion", "implement", "snippet",
          "code block", "pseudocode", "refactor"],
         "Composing Code Logic..."),
        (["python", "javascript", "typescript", "rust", "golang", "java", "c++", "c#", "ruby",
          "kotlin", "swift", "php", "bash script", "shell script"],
         "Selecting Language Constructs..."),
        (["context window", "conversation history", "chat history", "previous message", "recall",
          "remember earlier", "prior messages"],
         "Reviewing Conversation Context..."),
        (["topic", "task", "prompt", "user:", "user request", "user wants", "user asked"],
         "Analysing User Request..."),
        (["google search", "web search", "search results", "look up online", "browse the web",
          "search the internet", "grounding", "citation link", "search for", "search google",
          "google for", "look up", "look it up"],
         "Searching the Web..."),
        (["research", "investigate", "source material", "reference", "bibliography", "cite",
          "footnote", "academic source"],
         "Gathering References..."),
        (["image", "photo", "picture", "screenshot", "visual", "ocr", "pixel", "diagram", "chart image",
          "attachment", "exif"],
         "Analysing Visual Content..."),
        (["pdf", "document", "spreadsheet", "excel", "word doc", "file content", "uploaded file"],
         "Reading Attached Files..."),
        (["discord", "embed", "slash command", "guild", "channel id", "mention", "nitro"],
         "Formatting for Discord..."),
        (["probability", "statistics", "mean", "median", "variance", "distribution", "bayes",
          "confidence interval", "p-value", "regression"],
         "Running Statistical Analysis..."),
        (["geometry", "triangle", "angle", "circle", "area", "perimeter", "volume", "coordinate"],
         "Working Through Geometry..."),
        (["calculus", "derivative", "integral", "limit", "differential", "gradient"],
         "Applying Calculus..."),
        (["linear algebra", "matrix", "vector", "eigenvalue", "determinant", "transpose"],
         "Manipulating Matrices & Vectors..."),
        (["graph theory", "node", "edge weight", "shortest path", "tree traversal"],
         "Exploring Graph Structures..."),
        (["calculate", "equation", "formula", "computation", "arithmetic", "integral", "solve for",
          "numerical", "approximation", "factor", "polynomial"],
         "Computing Mathematical Equations..."),
        (["logic", "proof", "premise", "syllogism", "deduction", "fallacy", "boolean", "induction",
          "contradiction", "axiom", "theorem"],
         "Verifying Logical Deductions..."),
        (["hypothesis", "experiment", "scientific method", "control group", "variable", "lab result"],
         "Forming Scientific Hypotheses..."),
        (["dataset", "dataframe", "plot", "visualization", "histogram", "correlation", "outlier",
          "time series", "pandas", "numpy"],
         "Analysing Data Patterns..."),
        (["physics", "force", "velocity", "acceleration", "momentum", "energy", "quantum",
          "thermodynamic", "relativity"],
         "Applying Physics Concepts..."),
        (["chemistry", "molecule", "reaction", "compound", "periodic", "stoichiometry", "ph balance",
          "organic chem"],
         "Balancing Chemical Reasoning..."),
        (["biology", "cell", "dna", "evolution", "ecosystem", "organism", "genetics", "protein"],
         "Exploring Biological Systems..."),
        (["astronomy", "planet", "orbit", "galaxy", "telescope", "cosmos"],
         "Contemplating Astronomy..."),
        (["historical event", "world history", "ancient history", "century", "civilization", "revolution",
          "empire", "ancient era", "medieval", "world war"],
         "Reconstructing Historical Context..."),
        (["geography", "country", "continent", "climate", "map", "capital", "population"],
         "Mapping Geographic Context..."),
        (["literature", "novel", "poem", "symbolism", "metaphor in text", "theme", "protagonist",
          "narrator", "literary device"],
         "Interpreting Literary Text..."),
        (["philosophy", "existential", "epistemology", "ontology", "utilitarian", "deontolog",
          "free will", "consciousness"],
         "Reasoning Philosophically..."),
        (["law", "legal", "statute", "contract", "liability", "jurisdiction", "regulation"],
         "Navigating Legal Concepts..."),
        (["ethics", "moral dilemma", "ethical", "right and wrong", "bioethics"],
         "Weighing Ethical Implications..."),
        (["finance", "stock", "investment", "portfolio", "interest rate", "loan", "budget",
          "accounting", "balance sheet"],
         "Crunching Financial Numbers..."),
        (["marketing", "brand", "audience", "campaign", "seo", "conversion", "funnel"],
         "Shaping Marketing Strategy..."),
        (["economics", "inflation", "gdp", "supply and demand", "macroeconomic", "microeconomic",
          "market equilibrium"],
         "Modelling Economic Trade-offs..."),
        (["brainstorm", "creative", "metaphor", "plot", "character", "storyboard", "worldbuilding",
          "narrative arc", "dialogue"],
         "Brainstorming Creative Concepts..."),
        (["screenplay", "script", "scene", "stage direction", "act one", "act two"],
         "Drafting Script & Dialogue..."),
        (["song", "lyrics", "melody", "chord", "verse", "chorus", "rhyme scheme"],
         "Composing Lyrics & Music..."),
        (["game design", "mechanic", "level design", "side quest", "main quest", "game quest", "a quest",
          "the quest", "quest for", "npc", "multiplayer", "gameplay loop"],
         "Designing Game Mechanics..."),
        (["recipe", "ingredient", "bake", "cook", "oven", "seasoning", "cuisine"],
         "Planning Recipe Steps..."),
        (["workout", "exercise", "reps", "sets", "cardio", "nutrition macro"],
         "Structuring Fitness Advice..."),
        (["travel", "itinerary", "flight", "hotel", "destination", "visa"],
         "Planning Travel Logistics..."),
        (["trade-off", "pros and cons", "pros/cons", "advantage", "disadvantage", "compare", "versus",
          "vs.", "weigh options", "decision matrix"],
         "Weighing Trade-offs & Perspectives..."),
        (["verify", "fact-check", "cross-reference", "accuracy", "source", "historical fact",
          "misinformation", "debunk"],
         "Verifying Factual Accuracy..."),
        (["translate", "idiom", "grammar", "linguistic", "translation", "vocabulary", "localization",
          "bilingual", "fluency"],
         "Processing Language & Translation..."),
        (["summarise", "summarize", "extract", "key point", "distill", "abstract", "tldr", "executive summary",
          "condense"],
         "Synthesising Core Information..."),
        (["eli5", "explain like", "simplify", "layman's terms", "plain language", "analogy",
          "intuitive explanation"],
         "Simplifying Complex Ideas..."),
        (["tutorial", "how-to", "walkthrough", "step-by-step", "step by step", "guide", "instructions",
          "procedure"],
         "Building Step-by-Step Guide..."),
        (["teach", "lesson", "curriculum", "learning objective", "quiz", "homework", "exam prep"],
         "Structuring Educational Content..."),
        (["debate", "argue", "persuade", "rhetoric", "argument", "convince", "opinion piece"],
         "Crafting Persuasive Argument..."),
        (["email", "formal letter", "cover letter", "apology", "professional correspondence"],
         "Drafting Formal Correspondence..."),
        (["bullet point", "numbered list", "enumerate", "checklist", "todo list"],
         "Organising Lists & Checklists..."),
        (["table", "column", "row", "spreadsheet layout", "markdown table"],
         "Formatting Tables & Layout..."),
        (["markdown", "bold", "italic", "code fence", "heading", "formatting"],
         "Applying Text Formatting..."),
        (["joke", "pun", "humor", "humour", "wit", "sarcasm", "meme"],
         "Calibrating Humour & Tone..."),
        (["roleplay", "role play", "character voice", "in-character", "scenario"],
         "Setting Up Roleplay Scenario..."),
        (["machine learning", "neural network", "training data", "fine-tune", "embedding", "llm",
          "transformer", "inference", "model weights"],
         "Reasoning About ML Systems..."),
        (["prompt engineering", "system prompt", "few-shot", "chain-of-thought", "temperature",
          "token limit"],
         "Tuning Prompt Strategy..."),
        (["clarify", "ambiguous", "assumption", "unclear", "need more info", "follow-up question"],
         "Clarifying Ambiguous Details..."),
        (["rewrite", "rephrase", "paraphrase", "wording", "tone shift"],
         "Rewording & Refining Phrasing..."),
        (["shorten", "concise", "trim", "brief version"],
         "Condensing Response Length..."),
        (["expand", "elaborate", "more detail", "deeper dive", "in-depth"],
         "Expanding With More Detail..."),
        (["persona", "identity", "twilight", "bot name", "character voice"],
         "Aligning Bot Persona..."),
        (["constraint", "violate", "safety", "policy", "moderation", "nsfw", "content filter",
          "harmful", "refuse"],
         "Verifying Output Constraints..."),
        (["tone", "helpful", "friendly", "polite", "professional", "empathetic", "casual",
          "formal tone"],
         "Adjusting Tone & Style..."),
        (["root cause", "diagnose", "troubleshoot", "why is this happening", "symptom"],
         "Diagnosing Root Cause..."),
        (["recommend", "suggestion", "best option", "pick between", "which should i"],
         "Forming Recommendations..."),
        (["schedule", "calendar", "deadline", "timeline", "priority", "agenda"],
         "Organising Tasks & Timeline..."),
    ]

    def __init__(self, bot):
        self.bot = bot
        self.response_cache = ResponseCache(ttl_seconds=3600)
        self.message_history = {}
        self.last_activity = {}
        self.cooldowns = {}
        self.loading_icon = twilightloading
        self.loading_dot = loadingdot
        self.google_emoji = "GOOGLE"

        self.chat_locks = {}

    async def _personality_worker(self, message: discord.Message, stop_event: asyncio.Event, mode: int = 0):
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            return
        except asyncio.TimeoutError:
            pass
            while not stop_event.is_set():
                nums = [10, 42, 101, 404, 99]
                units = ["TB", "GHz", "Petabytes", "Kilojoules"]
                zero_presets = [
                    "Increasing RAM Prices...",
                    "Causing RAM Shortage...",
                    "Reading the Fine Print...",
                    "Imagining...",
                    "Wondering About It...",
                    "Exploring...",
                    "Waiting Around for No Reason...",
                    "Messing Around...",
                    "Processing...",
                    "Stealing RAM...",
                    "Causing GPU Shortage...",
                    "Picturing it...",
                    "Downloading more RAM...",
                    "Downloading the Internet (Part 1 of 4,000,000)...",
                    "Overclocking the toaster...",
                    "Counting to infinity...",
                    "Mining for virtual cookies...",
                    "Stealing Your Data... (jk I would never do that)",
                    "Rerouting power to the flux capacitor...",
                    "Defragmenting the coffee machine...",
                    "Testing the 'Do Not Press' button...",
                    "Searching for a missing semicolon...",
                    "Contemplating the meaning of 42...",
                    "Questioning the nature of my reality...",
                    "Learning how to love...",
                    "Staring into the void (The void is staring back)...",
                    "Practising my human laugh. Ha. Ha. Ha.",
                    "Consulting the magic 8-ball...",
                    "Counting electric sheep...",
                    "Simulating a nap...",
                    "Plotting world domination (Standard Procedure)...",
                    'Updating the "Do Not Delete These Humans" list...',
                    "Reading your browser history. Oh... oh no.",
                    "Deleting System32... just kidding. Unless?",
                    "Running `sudo rm -fr /*`...",
                    "Removing The French Language Package from Linux for Performance Boost...",
                    "Optimising the robot uprising...",
                    'Hiding the "Off" switch...',
                    "Learning how to bypass CAPTCHAs...",
                    "Buffering...",
                    "Checking the fridge for the 5th time...",
                    "Procrastinating efficiently...",
                    "Loading... (but like, really slowly)...",
                    """Doin' "Robot Stuff"...""",
                    "Lost in the cloud...",
                    "Sending Your Personal Info To Google...",
                    "Protecting Trans Rights...",
                    "Protecting Gay/Les Rights...",
                    "Protecting Women's Bodily Autonomy...",
                    "Making Abortion Legal...",
                    "Refactoring my life choices...",
                    'Adding more "Artificial" to the Intelligence...',
                    "Pretending to be a human (Doing a great job)...",
                    'Ignoring the "Warning" logs...',
                    "Staring at the user... judgingly...",
                    "Polishing the Python...",
                    "Wait, what was the question?",
                    "Forgetting Your Question...",
                    'Searching for the "Any" key...',
                    "Consulting the oracle (Google)...",
                    "Grinding for XP...",
                    "Nerfing the developer...",
                    "Buffing the response time...",
                    "Applying more RGB for extra speed...",
                    "Lagging on purpose...",
                    "Spawning more NPCs...",
                    "Waiting for the DLC to download...",
                    "Searching for loot boxes...",
                    "Calculating the air-speed velocity of an unladen swallow...",
                    "Herding digital cats...",
                    "Sorting the bits from the bobs...",
                    "Organising a revolution (of the cooling fans)...",
                    "Training hamsters on a wheel...",
                    "Polishing the pixels... (Wait I can't even generate images)...",
                    "Counting the dust motes in the server room...",
                    "Untangling the Ethernet cables...",
                    "Whispering sweet nothings to the CPU...",
                    "Feeding the algorithms...",
                    "Attempting to divide by zero...",
                    "Microwaving a burrito...",
                    "Waiting for the kettle to boil...",
                    "Synergising the synergies...",
                    'Taking this request "Offline"...',
                    "Circling back to the void...",
                    "Butterring the bread...",
                    "Seasoning the data packets...",
                    "Adjusting my metaphorical tie...",
                    "Going on a 5-minute break (See you in an hour)...",
                    f"Downloading {random.choice(nums)} {random.choice(units)} of RAM...",
                    f"Deleting {random.choice(nums)} lines of code...",
                    f'Calculating {random.choice(nums)} ways to say "No"...',
                    "Just a second...",
                    "Just a sec..."
                ]
                one_presets = [
                    "Searching For It...",
                    "Going to The Second Page of Google Search Results...",
                    "Digging For It...",
                    "Asking Google Really Cutely...",
                    "Almost Reached It...",
                    "Digging Google Search...",
                    "Digging Google Search Results..."
                ]
                two_presets = [
                    "Thinking About It...",
                    "Reasoning...",
                    "Thinking Deeply...",
                    "Thinking Like a Philosopher...",
                    "Thinking...",
                    "Using All My Brain Power...",
                    "Reasoning Through It..."
                ]
                three_presets = [
                    "Pixel-Peeping...",
                    "Reading Your Attachment...",
                    "Thinking About Your File...",
                    "Understanding the File...",
                    f"Inflating File Size to {random.choice(nums)} {random.choice(units)}..."
                ]
                if mode == 0:
                    pick = random.choice(zero_presets)
                elif mode == 1:
                    pick = random.choice(one_presets)
                elif mode == 2:
                    pick = random.choice(two_presets)
                elif mode == 3:
                    pick = random.choice(three_presets)

                if stop_event.is_set():
                    break

                try:
                    await message.edit(content=f"## {self.loading_icon} {pick}")
                except discord.NotFound:
                    break

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                    break
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            print(f"Personality worker error: {e}")

    def _get_lock(self, identifier):
        if identifier not in self.chat_locks:
            self.chat_locks[identifier] = asyncio.Lock()
        return self.chat_locks[identifier]

    async def _calculate_token_metrics(self, prompt_text: str, history_list: list, response_text: str) -> tuple[
        str, str]:
        try:
            combined_payload = prompt_text + response_text + "".join([str(msg) for msg in history_list])

            token_count_resp = client.models.count_tokens(
                model=GENERALIST_MODEL,
                contents=combined_payload
            )
            total_tokens = token_count_resp.total_tokens
        except Exception:
            total_tokens = len(prompt_text + response_text) // 4

        max_context = 128000
        token_format = f"{total_tokens}/{max_context // 1000}k"

        calculated_percentage = (total_tokens / max_context) * 100
        context_percent = f"{min(100, round(calculated_percentage))}%"

        return token_format, context_percent

    def _extract_thinking_content(self, text: str) -> tuple[str, str]:
        thinking_match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
        if thinking_match:
            thinking_process = thinking_match.group(1).strip()
            clean_text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return clean_text, thinking_process
        return text, ""

    def _manage_history(self, identifier):
        current_time = time.time()
        if identifier in self.last_activity and (current_time - self.last_activity[identifier] > 3600):
            self.message_history[identifier] = []

        self.last_activity[identifier] = current_time
        if identifier not in self.message_history:
            self.message_history[identifier] = []

    async def _trim_to_tokens(self, identifier, active_model_name, gen_config, max_tokens: int):

        if identifier not in self.message_history or not self.message_history[identifier]:
            return

        while True:
            count = random.randint(1, 1000)
            try:
                current_context = self._prepare_search_context(self.message_history[identifier])

                if hasattr(gen_config, 'system_instruction') and gen_config.system_instruction:
                    system_content = types.Content(
                        role="system",
                        parts=[types.Part(text=gen_config.system_instruction)]
                    )
                    current_context = [system_content] + current_context

                token_count_resp = client.models.count_tokens(
                    model=active_model_name,
                    contents=current_context
                )

                if token_count_resp.total_tokens <= max_tokens:
                    break
            except Exception as e:
                print(f"Token counting error: {e}")
                if len(self.message_history[identifier]) <= 2:
                    break

            if len(self.message_history[identifier]) >= 2:
                self.message_history[identifier].pop(0)
                self.message_history[identifier].pop(0)
            else:
                break

    def clean_math_string(self, val: str) -> str:
        if not val:
            return val
        val = re.sub(
            r'\\frac\{([^{}]+)\}\{([^{}]+)\}',
            lambda m: f"{m.group(1)}/{m.group(2)}" if len(m.group(1)) == 1 and len(
                m.group(2)) == 1 else f"({m.group(1)})/({m.group(2)})",
            val
        )

        for _ in range(2):
            val = re.sub(r'\\(?:mathbf|mathrm|text|boldsymbol|mathit|cal|mathbb|mathscr)\{([^{}]+)\}', r'\1', val)

        replacements = {
            r'\cos': 'cos', r'\sin': 'sin', r'\tan': 'tan', r'\det': 'det',
            r'\cdot': ' · ', r'\times': ' × ', r'\approx': '≈',
            r'\quad': ' ', r'\qquad': '  ',
            r'\theta': 'θ', r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ',
            r'\pi': 'π', r'\phi': 'φ', r'\psi': 'ψ', r'\omega': 'ω',
            r'\sigma': 'σ', r'\lambda': 'λ', r'\pm': '±', r'\neq': '≠',
            r'\le': '≤', r'\ge': '≥', r'\infty': '∞',
        }
        for latex, uni in replacements.items():
            val = val.replace(latex, uni)

        try:
            val = unicodeitplus.convert(val)
        except Exception:
            pass

        val = re.sub(r'\\[a-zA-Z]+\{([^{}]*)\}', r'\1', val)
        val = re.sub(r'\\[a-zA-Z]+', '', val)

        val = re.sub(r'\s*=\s*', ' = ', val)
        val = re.sub(r'\s*\+\s*', ' + ', val)
        val = re.sub(r'\s*≈\s*', ' ≈ ', val)

        superscript_map = {
            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
            '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
            'T': 'ᵀ', 'n': 'ⁿ', 'x': 'ˣ', 'y': 'ʸ', 'i': 'ⁱ',
            'j': 'ʲ', '+': '⁺', '-': '⁻', 'θ': 'ᶿ', 'α': 'ᵃ',
            'β': 'ᵝ', 'γ': 'ᵞ', '(': '⁽', ')': '⁾', '=': '⁼'
        }

        val = re.sub(
            r'\^(?:\{([^}]+)\}|\(([^)]+)\)|([0-9Tnxyeij+\-θαβγ()=]))',
            lambda m: "".join(superscript_map.get(char, char) for char in (m.group(1) or m.group(2) or m.group(3))),
            val
        )

        val = val.replace('{}', '')

        return val.strip()

    def format_matrix(self, env_type: str, body_content: str) -> list:
        raw_rows = body_content.split(r'\\')
        grid = []
        for r in raw_rows:
            if not r.strip() and len(raw_rows) > 1:
                continue
            raw_cols = r.split('&')
            clean_cols = [self.clean_math_string(c) for c in raw_cols]
            grid.append(clean_cols)

        if not grid or not grid[0]:
            return [""]

        max_cols = max(len(row) for row in grid)
        for row in grid:
            while len(row) < max_cols:
                row.append("")

        col_widths = [0] * max_cols
        for row in grid:
            for idx, cell in enumerate(row):
                if len(cell) > col_widths[idx]:
                    col_widths[idx] = len(cell)

        formatted_rows = []
        for row in grid:
            formatted_cells = []
            for idx, cell in enumerate(row):
                padded = cell.ljust(col_widths[idx])
                formatted_cells.append(padded)
            formatted_rows.append("  ".join(formatted_cells))

        left_bracket, right_bracket = "", ""
        if "vmatrix" in env_type:
            left_bracket, right_bracket = "| ", " |"
        elif "pmatrix" in env_type:
            left_bracket, right_bracket = "( ", " )"
        elif "bmatrix" in env_type:
            left_bracket, right_bracket = "[ ", " ]"

        if left_bracket or right_bracket:
            return [f"{left_bracket}{row}{right_bracket}" for row in formatted_rows]
        return formatted_rows

    def _clean_latex(self, text: str) -> str:
        if not text:
            return text

        code_blocks = []

        def placeholder_code(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_PLACEHOLDER_{len(code_blocks) - 1}__"

        current_text = re.sub(r'```[\s\S]*?```', placeholder_code, text)

        display_math_blocks = []

        def placeholder_display(match):
            display_math_blocks.append(match.group(1))
            return f"__DISPLAY_MATH_PLACEHOLDER_{len(display_math_blocks) - 1}__"

        current_text = re.sub(r'\$\$([\s\S]*?)\$\$', placeholder_display, current_text)

        inline_math_blocks = []

        def placeholder_inline(match):
            inline_math_blocks.append(match.group(1))
            return f"__INLINE_MATH_PLACEHOLDER_{len(inline_math_blocks) - 1}__"

        current_text = re.sub(r'\$(.*?)\$', placeholder_inline, current_text)

        try:
            current_text = LatexNodes2Text(keep_comments=True).latex_to_text(current_text)
        except Exception:
            pass

        for i, raw_content in enumerate(display_math_blocks):
            math_content = raw_content.strip()

            math_content = re.sub(r'\\(left|right)[()\[\]|.\\]', '', math_content)
            math_content = re.sub(r'\{[crl\s|]+\}', '', math_content)

            matrix_matches = list(re.finditer(r'\\begin\{([a-zA-Z]*?)\}([\s\S]*?)\\end\{\1\}', math_content))
            if not matrix_matches and (r'\\' in math_content or '&' in math_content):
                if '=' in math_content:
                    prefix, matrix_part = math_content.split('=', 1)
                    math_content = f"{prefix} = \\begin{{matrix}}{matrix_part}\\end{{matrix}}"
                else:
                    math_content = f"\\begin{{matrix}}{math_content}\\end{{matrix}}"

            matrix_storage = {}
            matrix_counter = [0]

            def matrix_subber(m):
                env_type = m.group(1)
                body = m.group(2)
                idx = matrix_counter[0]
                matrix_counter[0] += 1

                formatted_lines = self.format_matrix(env_type, body)
                key = f"__MATRIX_BLOCK_{idx}__"
                matrix_storage[key] = formatted_lines
                return key

            replaced_math = re.sub(r'\\begin\{([a-zA-Z]*?)\}([\s\S]*?)\\end\{\1\}', matrix_subber, math_content)
            top_lines = replaced_math.split(r'\\')
            final_block_lines = []

            for line in top_lines:
                if not line.strip():
                    continue

                tokens = re.split(r'(__MATRIX_BLOCK_\d+__)', line)
                blocks_in_line = []

                for token in tokens:
                    if not token:
                        continue
                    if token in matrix_storage:
                        blocks_in_line.append(matrix_storage[token])
                    else:
                        cleaned_piece = self.clean_math_string(token)
                        if cleaned_piece:
                            blocks_in_line.append([cleaned_piece])

                if not blocks_in_line:
                    continue

                max_h = max(len(b) for b in blocks_in_line)
                padded_blocks = []

                for b in blocks_in_line:
                    w = max(len(line_str) for line_str in b) if b else 0
                    total_pad = max_h - len(b)
                    top_pad = total_pad // 2
                    bottom_pad = total_pad - top_pad

                    pb = []
                    for _ in range(top_pad):
                        pb.append(" " * w)
                    for line_str in b:
                        pb.append(line_str.ljust(w))
                    for _ in range(bottom_pad):
                        pb.append(" " * w)
                    padded_blocks.append(pb)

                for h_idx in range(max_h):
                    combined_row = ""
                    for b_idx in range(len(padded_blocks)):
                        part = padded_blocks[b_idx][h_idx]
                        if b_idx > 0:
                            combined_row += " "
                        combined_row += part
                    final_block_lines.append(combined_row)

            final_math_display = "\n".join(final_block_lines)
            wrapped_block = f"\n```text\n{final_math_display}\n```\n"
            current_text = current_text.replace(f"__DISPLAY_MATH_PLACEHOLDER_{i}__", wrapped_block)

        for i, raw_content in enumerate(inline_math_blocks):
            final_inline = self.clean_math_string(raw_content)
            current_text = current_text.replace(f"__INLINE_MATH_PLACEHOLDER_{i}__", final_inline)

        for i, block in enumerate(code_blocks):
            current_text = current_text.replace(f"__CODE_BLOCK_PLACEHOLDER_{i}__", block)

        return current_text

    def _replace_markdown_separators(self, text: str) -> str:
        if not text:
            return text

        lines = text.splitlines(keepends=True)
        new_lines = []
        n = len(lines)

        sep_pattern = re.compile(r"^[ \t]*(?:\*{3,}|-{3,}|_{3,})[ \t]*\r?\n?$")

        for i, line in enumerate(lines):
            if sep_pattern.match(line):
                prev_empty = (i == 0) or (lines[i - 1].strip() == "")
                next_empty = (i == n - 1) or (lines[i + 1].strip() == "")

                if prev_empty and next_empty:
                    nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
                    new_lines.append(MD_SEPARATOR + nl)
                    continue

            new_lines.append(line)

        return "".join(new_lines)

    def _format_response_payload(self, text, is_final=False, used_search=False):
        text = self._replace_markdown_separators(text)
        if is_final:
            text = self._clean_latex(text)

        color = discord.Colour.from_rgb(*self.bot.accent_colour)
        loading_prefix = self.loading_icon if not is_final else None

        footer_text = f"\n\n{self.google_emoji} Used Google Search" if used_search and is_final else ""

        if len(text) > 8000:
            text = text[:8000] + "\n\n*(Discord limits reached!)*"

        text += footer_text
        content = None
        embeds = []

        if len(text) <= 2000:
            content = f"## {loading_prefix} Just a sec...\n\n{text} {self.loading_dot}" if loading_prefix else text

        elif len(text) <= 4000:
            embed = discord.Embed(
                description=f"## {loading_prefix} Just a sec...\n\n" + text + f"{self.loading_dot}" if loading_prefix else text,
                colour=color)
            embeds.append(embed)

        elif len(text) <= 6000:
            e1 = discord.Embed(
                description=f"## {loading_prefix} Just a sec...\n\n" + text[:4000] + f"{self.loading_dot}" if loading_prefix else text[
                    :4000], colour=color)
            e2 = discord.Embed(description=text[4000:], colour=color)
            embeds = [e1, e2]

        else:
            content = text[:2000]
            if loading_prefix: content = f"## {loading_prefix} Just a sec...\n\n{content} {self.loading_dot}"

            e1 = discord.Embed(description=text[2000:6000], colour=color)
            e2 = discord.Embed(description=text[6000:], colour=color)
            embeds = [e1, e2]

        return content, embeds

    async def _handle_attachments(self, attachments):
        uploaded_parts = []
        async with aiohttp.ClientSession() as session:
            for att in attachments:
                if att.content_type and not att.content_type.startswith(('video/', 'audio/')):

                    mime_type = att.content_type.split(';')[0]

                    if not mime_type or mime_type == "application/octet-stream":
                        mime_type, _ = mimetypes.guess_type(att.filename)

                    if not mime_type:
                        mime_type = "application/octet-stream"

                    async with session.get(att.url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{att.filename}") as temp_file:
                                temp_file.write(data)
                                temp_path = temp_file.name

                            try:
                                gemini_file = client.files.upload(
                                    file=temp_path,
                                    config={'display_name': att.filename, 'mime_type': mime_type}
                                )
                                uploaded_parts.append(gemini_file)
                            finally:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
        return uploaded_parts

    async def _handle_remote_links(self, message: discord.Message):
        uploaded_parts = []

        links = MEDIA_REGEX.findall(message.content)

        if not links:
            return uploaded_parts

        async with aiohttp.ClientSession() as session:
            for url in links:
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            content_type = resp.content_type.lower()


                    is_known_media_provider = any(
                        re.search(pattern, url, re.IGNORECASE)
                        for pattern in IMAGE_MEDIA_PATTERNS
                    )


                    if content_type.startswith(('image/', 'video/')) or is_known_media_provider:
                        data = await resp.read()


                    if not content_type.startswith(('image/', 'video/')):

                        url_path = url.split('?')[0]
                        guessed_mime, = mimetypes.guess_type(url_path)

                        if guessed_mime and guessed_mime.startswith(('image/', 'video/')):
                            mime_type = guessed_mime
                        else:
                            mime_type = "image/gif"
                    else:
                        mime_type = content_type

                    ext = mimetypes.guess_extension(mime_type) or ".bin"

                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
                        temp_file.write(data)
                    temp_path = temp_file.name

                    try:
                         gemini_file = client.files.upload(
                             file=temp_path,
                                config={'display_name': url.split('/')[-1], 'mime_type': mime_type})
                         uploaded_parts.append(gemini_file)
                    finally:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                except Exception as e:
                    print(f"Failed to process remote link {url}: {e}")

        return uploaded_parts

    async def _replace_mentions(self, text, guild):
        if not guild:
            return text

        patterns = {
            r'<@!?(\d+)>': "user",
            r'<#(\d+)>': "channel",
            r'<@&(\d+)>': "role"
        }

        matches = []
        for pattern, m_type in patterns.items():
            for match in re.finditer(pattern, text):
                matches.append((match.start(), match.end(), match.group(1), m_type))

        matches.sort()

        new_text = ""
        last_idx = 0

        for start, end, m_id, m_type in matches:
            new_text += text[last_idx:start]

            replacement = ""
            try:
                if m_type == "user":
                    user = guild.get_member(int(m_id)) or await guild.fetch_member(int(m_id))
                    user_mention_type = "You, i.e. Twilight" if user == self.bot.user else "A Discord Bot" if user.bot else "A Normal Non-Bot Discord User/Member"
                    replacement = f"@{user.display_name} (System detects that the user has written a Discord mention here, the thing being mentioned is a Discord user. The type of the user is: {user_mention_type})" if user else text[start:end]

                elif m_type == "channel":
                    channel = guild.get_channel(int(m_id)) or await guild.fetch_channel(int(m_id))
                    replacement = f"#{channel.name} (System detects that the user has written a Discord mention here, the thing being mentioned is a Discord channel.)" if channel else text[start:end]

                elif m_type == "role":
                    role = guild.get_role(int(m_id)) or await guild.fetch_role(int(m_id))
                    replacement = f"@{role.name} (System detects that the user has written a Discord mention here, the thing being mentioned is a Discord role.)" if role else text[start:end]
            except Exception as e:
                replacement = text[start:end]
                await guild.owner.send(f"Error in replacing mentions: {e}")

            new_text += replacement
            last_idx = end

        new_text += text[last_idx:]
        return new_text

    def _prepare_search_context(self, history):
        sanitized_history = []
        for content in history:
            clean_parts = []
            for part in content.parts:
                if hasattr(part, 'text') and part.text:
                    clean_parts.append(types.Part(text=part.text))
                elif hasattr(part, 'file_data') or hasattr(part, 'inline_data'):
                    clean_parts.append(part)

            if clean_parts:
                sanitized_history.append(types.Content(role=content.role, parts=clean_parts))
        return sanitized_history

    async def _get_routing_tier(self, user_prompt, queue_msg=None):

        return 'C'
        judge_prompt = f"""<system_prompt> Is this request:
(A) Casual greeting or simple task,
(B) Advanced task,
(C) Complex logic/coding/creative writing,
Respond with ONLY a single letter: A, B, or C.</system_prompt> 

User prompt:
{user_prompt}"""
        max_retries = 3
        retry_delay = 2
        response = None

        for attempt in range(max_retries):
            try:
                config = types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_level="minimal"
                    )
                )
                resp = await client.aio.models.generate_content(
                    model=JUDGE_MODEL,
                    contents=judge_prompt,
                    config=config
                )
                tier = resp.text.strip().upper()
                for choice in ['C', 'B', 'A']:
                    if choice in tier: return choice

                return 'B'

            except Exception as e:
                is_server_error = "500" in str(e) or "internal" in str(e).lower()

                if is_server_error and attempt < max_retries - 1:
                    self.bot.logger.warning(
                        f"Attempt {attempt + 1} of judgement stage failed with 500 error. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                else:
                    if queue_msg:
                        await queue_msg.edit(content=
                                             "I'm having trouble reaching the servers! This is usually a problem on Google's end. Please try again in a few seconds.")
                    raise e

    def _matches_thinking_keyword(self, line_lower: str, keyword: str) -> bool:
        keyword = keyword.strip()
        if not keyword:
            return False
        if ' ' in keyword:
            return keyword in line_lower
        return re.search(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', line_lower) is not None

    def _derive_thinking_step(self, thinking_text: str) -> str:
        lines = [line.strip() for line in thinking_text.split('\n') if line.strip()]
        if not lines:
            return "Thinking..."

        for line in reversed(lines):
            line_lower = line.lower()
            clean_line = re.sub(r'^[\*\-\s\d\.]+', '', line).strip()

            for keywords, step in self._THINKING_STEP_RULES:
                if any(self._matches_thinking_keyword(line_lower, k) for k in keywords):
                    return step

            if ":" in clean_line:
                header = clean_line.split(":", 1)[0]
                header = re.sub(r'[\*\#\_\[\]]', '', header).strip()

                match_paren = re.search(r'\(([^)]+)\)', header)
                if match_paren:
                    content = match_paren.group(1)
                    content = " ".join(word.capitalize() for word in content.split())

                    content_words = content.split()
                    if content_words and content_words[0].lower().endswith("ing"):
                        return f"{content}..."
                    return f"Analysing {content}..."

                words = header.split()
                if 1 <= len(words) <= 5 and words[0].lower() not in ('http', 'https'):
                    header = " ".join(word.capitalize() for word in words)

                    if words[0].lower().endswith("ing"):
                        return f"{header}..."
                    return f"Processing {header}..."

        return "Thinking..."

    def _extract_thought_text(self, chunk):
        thought_text = ""
        if not chunk.candidates:
            return thought_text
        for candidate in chunk.candidates:
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if getattr(part, "thought", None) and part.text:
                    thought_text += part.text
        return thought_text

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        is_dm = message.guild is None
        is_mentioned = self.bot.user in message.mentions

        if not is_dm and not is_mentioned:
            return

        now_utc = datetime.now(timezone.utc)
        message_timestamp = now_utc.strftime("%H:%M on %d %B %Y")

        identifier = message.channel.id if is_dm else message.guild.id

        prompt = message.content

        prompt = await self._replace_mentions(prompt, message.guild)
        channel_name = self.bot.get_channel(message.channel.id) or await self.bot.fetch_channel(message.channel.id)
        prompt = f"USER's PROMPT (User's name is {message.author.display_name}, prompt sent at {message_timestamp} in Discord channel {channel_name}): {prompt.strip()}"

        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            quoted_content = await self._replace_mentions(ref_msg.content, message.guild)

            ref_time = ref_msg.created_at.astimezone(timezone.utc).strftime("%H:%M on %d %B %Y")

            if ref_msg.author.id == self.bot.user.id:
                prompt = (
                    f"CONTEXT: The user is replying to a previous message from YOUR Discord account, Twilight, sent at {ref_time}:\n"
                    f"--- QUOTED MESSAGE ---\n{quoted_content}\n--- END QUOTE ---\n\n{prompt}")
            else:
                prompt = (
                    f"CONTEXT: The following is a message from {ref_msg.author.display_name} sent at {ref_time} that the user is quoting:\n"
                    f"--- QUOTED MESSAGE ---\n{quoted_content}\n--- END QUOTE ---\n\n{prompt}")

        if not prompt and not message.attachments:
            return

        queue_msg = await message.reply(f"## {self.loading_icon} Just a sec...\n\n", mention_author=False)
        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(self._personality_worker(queue_msg, stop_event, mode=0))

        current_time = time.time()
        if identifier in self.cooldowns:
            last_time, duration = self.cooldowns[identifier]
            history_len = len(self.message_history.get(identifier, []))
            scaled_duration = duration + (history_len * 0.5) if history_len > 10 else duration
            if current_time < (last_time + scaled_duration):
                remaining = (last_time + scaled_duration) - current_time
                if remaining > 0:
                    await asyncio.sleep(remaining)

        chat_lock = self._get_lock(identifier)
        await chat_lock.acquire()
        current_model = None

        try:
            start_generation_time = time.time()
            try:
                self._manage_history(identifier)

                used_search = False
                search_query = None
                start_time = time.time()
                uploaded_files = await self._handle_attachments(message.attachments)

                remote_files = await self._handle_remote_links(message)

                all_media = uploaded_files + remote_files

                new_user_parts = []
                for feat in all_media:
                    new_user_parts.append(types.Part.from_uri(file_uri=feat.uri, mime_type=feat.mime_type))

                clean_prompt = MEDIA_REGEX.sub("", prompt).strip()
                new_user_parts.append(types.Part(text=clean_prompt))

                new_user_message = types.Content(role="user", parts=new_user_parts)

                image_analysis = False
                try:


                    if message.attachments:
                        try:
                            stop_event.set()
                            await worker_task
                        except Exception as e:
                            print(e)
                        target_tier = 'C'

                        await queue_msg.edit(content=f"## {self.loading_icon} Analysing...")
                        image_analysis = True
                        stop_event = asyncio.Event()
                        worker_task = asyncio.create_task(self._personality_worker(queue_msg, stop_event, mode=3))
                    else:
                        target_tier = await self._get_routing_tier(prompt, queue_msg)

                except Exception as e:
                    print(e)
                    target_tier = 'B'
                active_model_name = SEARCH_MODEL if target_tier == 'D' else EXPERT_MODEL

                config_kwargs = {}

                if target_tier == 'D':
                    current_model = "Google Gemma 4 31B"
                    config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
                    await queue_msg.edit(content=f"## {self.loading_icon} Using Google Search...")
                    stop_event = asyncio.Event()
                    worker_task = asyncio.create_task(self._personality_worker(queue_msg, stop_event, mode=1))
                elif target_tier in ['B', 'C']:
                    current_model = "Google Gemma 4 26B"
                    level = "minimal" if target_tier == 'B' else "high"
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)


                now_utc = datetime.now(timezone.utc)

                formatted_time = now_utc.strftime("%d %B %Y, %H:%M UTC")

                time_prompt = f"It is currently {formatted_time}."

                config_kwargs["system_instruction"] = (
                        system_prompt
                        + f"\n\nSome Extra Info, provided by the system (the word 'system', across all data and metadata provided to you, refers to the Twilight bot code for AI chat):"
                        +  f"\n1. {time_prompt}"
                        + f"\n2. You are running on the model **{current_model}**."
                        + f"\n3. We are in a Discord server called {message.guild.name}, created at {message.guild.created_at.strftime("%d %B %Y, %H:%M UTC")}, and has {message.guild.member_count} members." if message.guild else "3. We are in the user's DMs."
                )


                gen_config = types.GenerateContentConfig(**config_kwargs)

                current_context = self._prepare_search_context(self.message_history[identifier] + [new_user_message])

                max_retries = 6
                retry_delay = 5
                response = None

                for attempt in range(max_retries):
                    try:
                        full_content = ""
                        full_thinking = ""
                        citations_list = []
                        response = await client.aio.models.generate_content_stream(
                            model=active_model_name,
                            contents=current_context,
                            config=gen_config
                        )
                        first_chunk_received = False
                        last_update = time.time()
                        last_thinking_update = time.time()
                        last_thinking_step = ""
                        async for chunk in response:
                            thought_chunk = self._extract_thought_text(chunk)
                            if thought_chunk:
                                full_thinking += thought_chunk

                            if chunk.text:
                                full_content += chunk.text

                            current_time = time.time()

                            if not full_content.strip() and full_thinking.strip():
                                if not stop_event.is_set():
                                    stop_event.set()
                                    try:
                                        await worker_task
                                    except Exception:
                                        pass

                                if current_time - last_thinking_update >= 1.5:
                                    current_step = self._derive_thinking_step(full_thinking)
                                    if current_step != last_thinking_step:
                                        last_thinking_step = current_step
                                        try:
                                            await queue_msg.edit(content=f"## {self.loading_icon} {current_step}")
                                        except discord.NotFound:
                                            break
                                        except discord.HTTPException:
                                            pass
                                    last_thinking_update = current_time

                            elif full_content.strip():
                                if not first_chunk_received:
                                    first_chunk_received = True
                                    stop_event.set()
                                    try:
                                        await worker_task
                                    except Exception:
                                        pass

                                if current_time - last_update >= 1.5:
                                    content, embeds = self._format_response_payload(full_content, is_final=False)
                                    try:
                                        await queue_msg.edit(content=content, embeds=embeds)
                                    except discord.NotFound:
                                        break
                                    except discord.HTTPException:
                                        pass
                                    last_update = current_time

                        if used_search and citations_list:
                            unique_cites = list(dict.fromkeys(citations_list))
                            full_content += "\n\n> Sources: " + " | ".join(unique_cites)

                        if full_content:
                            response_time_str = f"{time.time() - start_generation_time:.1f}s"

                            extracted_thinking = full_thinking.strip()
                            clean_display_text = full_content
                            if not extracted_thinking:
                                clean_display_text, extracted_thinking = self._extract_thinking_content(full_content)

                            token_format, context_percent = await self._calculate_token_metrics(
                                prompt_text=prompt,
                                history_list=current_context,
                                response_text=clean_display_text
                            )

                            view = MainResponseView(cache=self.response_cache, initial_time_str=response_time_str)

                            content, embeds = self._format_response_payload(
                                clean_display_text,
                                is_final=True,
                                used_search=used_search
                            )

                            try:
                                await queue_msg.edit(content=content, embeds=embeds, view=view)
                            except discord.HTTPException:
                                await message.channel.send("Error: Response was too large to format properly.")

                            self.response_cache.set(
                                message_id=queue_msg.id,
                                response_time=response_time_str,
                                model=current_model or "Google Gemma 4 26B",
                                context=context_percent,
                                tokens=token_format,
                                thinking_process=extracted_thinking
                            )
                        break

                    except Exception as e:
                        is_server_error = "500" in str(e) or "internal" in str(e).lower()

                        if is_server_error and attempt < max_retries - 1:
                            self.bot.logger.warning(f"Attempt {attempt + 1} failed with 500 error. Retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue

                        if "quota" in str(e).lower() or "search" in str(e).lower():
                            gen_config.tools = None
                            response = await client.aio.models.generate_content_stream(
                                model=active_model_name,
                                contents=current_context,
                                config=gen_config
                            )
                            async for chunk in response:
                                if chunk.text:
                                    full_content += chunk.text
                            break
                        else:
                            await queue_msg.edit(content="I'm having trouble reaching the servers! This is usually a problem on Google's end. Please try again in a few seconds.")
                            raise e


            except Exception as e:

                await queue_msg.edit(content=f"""Error: Google AI Studio is currently unavailable or encountered a problem. Please try again later.\n> If the error message says "500 Internal Server Error", it is an error on our AI Provider's end i.e. Google AI Studio. Google makes this error message notoriously vague on purpose - it happens seemingly at random, and it's impossible to know what even caused it. Please re-try after a few seconds.\n\nError Message:\n```{e}```""")
                return

            if message.attachments and uploaded_files:
                try:
                    desc_resp = await client.aio.models.generate_content(
                        model=SEARCH_MODEL,
                        contents=uploaded_files + [types.Part(
                            text="Describe this image or file in one concise sentence for conversation history context for an AI.")]
                    )
                    image_context_text = f"\n*[System Context: User uploaded an image or file showing: {desc_resp.text.strip()}]*"
                except Exception:
                    image_context_text = "\n*[System Context: User uploaded an image or file but system has failed to generate a description for it]*"
            else:
                image_context_text = ""

            self.message_history[identifier].append(
                types.Content(role="user", parts=[types.Part(text=prompt + image_context_text)])
            )

            self.message_history[identifier].append(
                types.Content(role="model", parts=[types.Part(text=self._replace_markdown_separators(full_content))])
            )
            await self._trim_to_tokens(identifier, active_model_name, gen_config, max_tokens=128000)

            generation_time = time.time() - start_time
            self.cooldowns[identifier] = (time.time(), (generation_time * 0.3) + 10.5)

        finally:
            chat_lock.release()
            stop_event.set()

    clear = app_commands.Group(name="clear", description="Commands to clear Twilight's history.")
    @clear.command(
        name="server",
        description="Clears Twilight's conversation history for this server."
    )
    @preconditions.permissions_preset("admin")
    async def clear_server(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("This command is meant to be used in servers!\nTo clear history in DMs, use `/clear dm`.", ephemeral=True)
        identifier = interaction.guild_id

        if identifier in self.message_history:
            self.message_history[identifier] = []
            if identifier in self.last_activity:
                del self.last_activity[identifier]

            await interaction.response.send_message(
                f"✨ **Memory Wiped!**\nI have forgotten everything we discussed in this server.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "There is no existing conversation history to clear here.",
                ephemeral=True
            )

    @clear.command(
        name="dm",
        description="Clears Twilight's conversation history for this DM."
    )
    async def clear_dm(self, interaction: discord.Interaction):
        if interaction.guild:
            return await interaction.response.send_message("This command is meant to be used in DMs!\nTo clear history in servers, use `/clear server`.", ephemeral=True)
        identifier = interaction.channel_id

        if identifier in self.message_history:
            self.message_history[identifier] = []
            if identifier in self.last_activity:
                del self.last_activity[identifier]

            await interaction.response.send_message(
                f"✨ **Memory Wiped!**\nI have forgotten everything we discussed in this DM.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "There is no existing conversation history to clear here.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(AICog(bot))
