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
import random # used by _trim_to_tokens()
import asyncio
from beacon import beacon_commands, preconditions
from datetime import datetime, timezone
from pylatexenc.latex2text import LatexNodes2Text
import unicodeitplus
import mimetypes
from dataclasses import dataclass
import io
import functools

# Import our English status msgs
from languages.english.statuses import StatusEngine, THINKING_STEP_CONVERSIONS

#NB: module still contains English hardcoded strings

client = genai.Client(api_key=gemini_api_key)

"""PRODUCTION EMOJIS"""
"""reportemoji = "<:ReportEmoji:1515283638164521031>"
#threedotemoji = "<:ThreedotEmoji:1515283624088436767>"
#retryemoji = "<:RetryEmoji:1515283585123483688>"
#backemoji = "<:BackEmoji:1515286702787395724>"
#twilightloading = "<a:twilight_loading_icon:1506347831605198981>"
#loadingdot = "<a:twilight_loading_dot:1506348237722878085>"""

reportemoji = "<:ReportEmoji:1516126283778756701>"
threedotemoji = "<:ThreedotEmoji:1516126288182644940>"
retryemoji = "<:RetryEmoji:1516126285775245352>"
backemoji = "<:BackEmoji:1516126262265909388>"
twilightloading = "<a:twilight_loading_icon:1516126476280398014>"
loadingdot = "<a:loadingdot:1516126281719218297>"

REPORT_CHANNEL=1516324617910878309

JUDGE_MODEL = "models/gemma-4-26b-a4b-it"
GENERALIST_MODEL = "models/gemma-4-26b-a4b-it"
EXPERT_MODEL = "models/gemma-4-26b-a4b-it"
SEARCH_MODEL = "models/gemma-4-31b-it"
MD_SEPARATOR = "𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖𝄖"

# PRE-COMPILING REGEX PATTERNS
MEDIA_REGEX = re.compile(r'(https?://\S+)', re.IGNORECASE)
IMAGE_MEDIA_PATTERNS = [
    r"giphy\.com",
    r"tenor\.com",
    r"imgur\.com",
    r"pinimg\.com",
    r"media\.giphy\.com",
    r"i\.giphy\.com"
]
THINKING_REGEX = re.compile(r"<think>(.*?)</think>", re.DOTALL)

LATEX_FRAC_REGEX = re.compile(r'\\frac\{([^{}]+)\}\{([^{}]+)\}')
LATEX_FONT_REGEX = re.compile(r'\\(?:mathbf|mathrm|text|boldsymbol|mathit|cal|mathbb|mathscr)\{([^{}]+)\}')
LATEX_COMMAND_BRACES_REGEX = re.compile(r'\\[a-zA-Z]+\{([^{}]*)\}')
LATEX_COMMAND_REGEX = re.compile(r'\\[a-zA-Z]+')
SPACED_EQUALS_REGEX = re.compile(r'\s*=\s*')
SPACED_PLUS_REGEX = re.compile(r'\s*\+\s*')
SPACED_APPROX_REGEX = re.compile(r'\s*≈\s*')
SUPERSCRIPT_REGEX = re.compile(r'\^(?:\{([^}]+)\}|\(([^)]+)\)|([0-9Tnxyeij+\-θαβγ()=]))')

CODE_BLOCK_REGEX = re.compile(r'```[\s\S]*?```')
DISPLAY_MATH_REGEX = re.compile(r'\$\$([\s\S]*?)\$\$')
INLINE_MATH_REGEX = re.compile(r'\$(.*?)\$')
LATEX_LEFT_RIGHT_REGEX = re.compile(r'\\(left|right)[()\[\]|.\\]')
LATEX_ALIGN_ALIGN_REGEX = re.compile(r'\{[crl\s|]+\}')
MATRIX_ENV_REGEX = re.compile(r'\\begin\{([a-zA-Z]*?)\}([\s\S]*?)\\end\{\1\}')

MD_SEP_REGEX = re.compile(r"^[ \t]*(?:\*{3,}|-{3,}|_{3,})[ \t]*\r?\n?$")

PAREN_HEADER_REGEX = re.compile(r'\(([^)]+)\)')
STRIP_MARKDOWN_REGEX = re.compile(r'[\*\#\_\[\]]')
LEADING_CLEAN_REGEX = re.compile(r'^[\*\-\s\d\.]+')
MENTION_PATTERNS = {
    re.compile(r'<@!?(\d+)>'): "user",
    re.compile(r'<#(\d+)>'): "channel",
    re.compile(r'<@&(\d+)>'): "role"
}
IMAGE_MEDIA_RE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in IMAGE_MEDIA_PATTERNS]
HEADER_COLON_REGEX = re.compile(r'^([^:]+):')

@functools.lru_cache(maxsize=1024)
def get_keyword_regex(keyword: str):
    return re.compile(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)')

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


class ReportReasonModal(discord.ui.Modal, title="Report Response"):
    reason = discord.ui.TextInput(
        label="Reason for report",
        style=discord.TextStyle.long,
        placeholder="Please describe why you are reporting this generation (e.g., incorrect formatting, harmful content, hallucination)...",
        required=True,
        max_length=1000
    )

    def __init__(self, message_to_report: discord.Message):
        super().__init__()
        self.message_to_report = message_to_report

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "**Response Reported Successfully:** This generation has been reported for internal review. Thank you!",
            ephemeral=True
        )

        report_channel = interaction.client.get_channel(REPORT_CHANNEL) or await interaction.client.fetch_channel(REPORT_CHANNEL)
        if not report_channel:
            print(f"Could not retrieve report channel.")
            return

        reporter = interaction.user
        original_content = self.message_to_report.content or "*(No text content - possibly embed-only)*"

        embed = discord.Embed(
            title="Response Report Received",
            colour=discord.Colour.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Reported By", value=f"{reporter.mention} ({reporter.id})", inline=True)
        embed.add_field(name="Channel Context", value=f"{interaction.channel.mention if interaction.guild else 'DMs'}",
                        inline=True)
        embed.add_field(name="Reason Provided", value=self.reason.value, inline=False)

        if len(original_content) > 1000:
            original_content = original_content[:1000] + "...\n*(Truncated due to length)*"

        embed.add_field(name="Original Response Text Fragment", value=f"```text\n{original_content}\n```", inline=False)
        embed.add_field(name="Jump to Message",
                        value=f"[Click Here to View Message]({self.message_to_report.jump_url})", inline=False)

        if self.message_to_report.embeds:
            embed_descs = []
            for idx, emb in enumerate(self.message_to_report.embeds):
                if emb.description:
                    desc_frag = emb.description[:300] + "..." if len(emb.description) > 300 else emb.description
                    embed_descs.append(f"Embed {idx + 1}: {desc_frag}")
            if embed_descs:
                embed.add_field(name="Contained Embed Summaries", value="\n".join(embed_descs), inline=False)

        await report_channel.send(embed=embed)


class MainResponseView(discord.ui.View):
    def __init__(self, cog, identifier, message_id: int | None, cache, initial_time_str: str = "0.0s",
                 timeout: float = 3600.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.identifier = identifier
        self.message_id = message_id
        self.cache = cache
        self.children[0].label = f" {initial_time_str} "

        if message_id:
            self.check_retry_status()

    def check_retry_status(self):
        active_id = self.cog._active_responses.get(self.identifier)
        metadata = self.cache.get(self.message_id)

        is_latest = (self.message_id == active_id)
        has_expired = False
        if metadata:
            # 5-minute absolute hard deadline threshold
            has_expired = (time.time() - metadata.timestamp > 300)

        if not is_latest or has_expired:
            self.children[1].disabled = True

    @discord.ui.button(label="0.0s", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def response_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.secondary,
                       emoji=discord.PartialEmoji.from_str(retryemoji), row=0)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_id = self.cog._active_responses.get(self.identifier)
        metadata = self.cache.get(interaction.message.id)

        is_latest = (interaction.message.id == active_id)
        has_expired = (time.time() - metadata.timestamp > 300) if metadata else True

        if not is_latest or has_expired:
            button.disabled = True
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "This response is no longer the active head of the conversation history or has expired.",
                ephemeral=True
            )
            return

        button.disabled = True
        await interaction.response.edit_message(view=self)

        if not interaction.message.reference:
            await interaction.followup.send("Cannot locate the original prompt reference.", ephemeral=True)
            return

        try:
            user_msg = await interaction.channel.fetch_message(interaction.message.reference.message_id)
        except Exception:
            await interaction.followup.send("Could not retrieve the original prompt from channel history.",
                                            ephemeral=True)
            return

        await self.cog.on_message(user_msg, retry_message=interaction.message)

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(threedotemoji), style=discord.ButtonStyle.secondary, row=0)
    async def overflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        overflow_view = OverflowButtonView(cog=self.cog, identifier=self.identifier, cache=self.cache)
        overflow_view.update_layout_from_cache(interaction.message.id)
        await interaction.response.edit_message(view=overflow_view)


class OverflowButtonView(discord.ui.View):
    def __init__(self, cog, identifier, cache, timeout: float = 3600.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.identifier = identifier
        self.cache = cache

    def update_layout_from_cache(self, message_id: int):
        metadata = self.cache.get(message_id)
        if metadata:
            self.children[0].label = f"Context: {metadata.context_percent}"
            self.children[1].label = f"Tokens: {metadata.token_format}"
            if not metadata.thinking_process:
                self.children[3].disabled = True

    @discord.ui.button(label="Context: --%", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def context_stat(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Tokens: --/--", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def token_stat(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Report Response", style=discord.ButtonStyle.danger,
                       emoji=discord.PartialEmoji.from_str(reportemoji), row=1)
    async def report_response(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReportReasonModal(message_to_report=interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Show Thinking Process", style=discord.ButtonStyle.secondary, row=1)
    async def show_thinking(self, interaction: discord.Interaction, button: discord.ui.Button):
        metadata = self.cache.get(interaction.message.id)
        if metadata and metadata.thinking_process:
            thinking_text = metadata.thinking_process

            if len(thinking_text) > 1990:
                file_stream = io.BytesIO(thinking_text.encode('utf-8'))
                discord_file = discord.File(fp=file_stream, filename="thinking_process.txt")

                await interaction.response.send_message(
                    "**Twilight's Thinking Process:**\n*(The thinking process was too long to display in a Discord message, so it has been attached as a file.)*",
                    file=discord_file,
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"**Twilight's Thinking Process:**\n\n{thinking_text}\n",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "No historical thinking process was recorded for this response.",
                ephemeral=True
            )

    @discord.ui.button(label="Back", emoji=discord.PartialEmoji.from_str(backemoji),
                       style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        metadata = self.cache.get(interaction.message.id)
        time_str = metadata.response_time_str if metadata else "0.0s"

        main_view = MainResponseView(
            cog=self.cog,
            identifier=self.identifier,
            message_id=interaction.message.id,
            cache=self.cache,
            initial_time_str=time_str
        )
        await interaction.response.edit_message(view=main_view)

class AICog(commands.Cog):
    # Convert AI steps into status update messages
    _THINKING_STEP_RULES = THINKING_STEP_CONVERSIONS

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
        self._active_responses = {}

    async def _personality_worker(self, message: discord.Message, stop_event: asyncio.Event, mode: int = 0):
        # We fire up a fresh engine instance for this specific worker loop run!
        # This keeps the history completely isolated to this message-response.
        engine = StatusEngine()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            return
        except asyncio.TimeoutError:
            pass
            while not stop_event.is_set():
                if stop_event.is_set():
                    break

                picked_respose = engine.get_next_unused_status(mode=mode)
                try:
                    await message.edit(content=f"## {self.loading_icon} {picked_respose}")
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

        max_context = 64000
        token_format = f"{total_tokens}/{max_context // 1000}k"

        calculated_percentage = (total_tokens / max_context) * 100
        context_percent = f"{min(100, calculated_percentage):.1f}%"

        return token_format, context_percent

    def _extract_thinking_content(self, text: str) -> tuple[str, str]:
        thinking_match = THINKING_REGEX.search(text)
        if thinking_match:
            thinking_process = thinking_match.group(1).strip()
            clean_text = THINKING_REGEX.sub("", text).strip()
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
            val = LATEX_FONT_REGEX.sub(r'\1', val)

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

        val = LATEX_COMMAND_BRACES_REGEX.sub(r'\1', val)
        val = LATEX_COMMAND_REGEX.sub('', val)

        val = SPACED_EQUALS_REGEX.sub(' = ', val)
        val = SPACED_PLUS_REGEX.sub(' + ', val)
        val = SPACED_APPROX_REGEX.sub(' ≈ ', val)

        superscript_map = {
            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
            '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
            'T': 'ᵀ', 'n': 'ⁿ', 'x': 'ˣ', 'y': 'ʸ', 'i': 'ⁱ',
            'j': 'ʲ', '+': '⁺', '-': '⁻', 'θ': 'ᶿ', 'α': 'ᵃ',
            'β': 'ᵝ', 'γ': 'ᵞ', '(': '⁽', ')': '⁾', '=': '⁼'
        }

        val = SUPERSCRIPT_REGEX.sub(
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

        current_text = CODE_BLOCK_REGEX.sub(placeholder_code, text)

        display_math_blocks = []
        def placeholder_display(match):
            display_math_blocks.append(match.group(1))
            return f"__DISPLAY_MATH_PLACEHOLDER_{len(display_math_blocks) - 1}__"

        current_text = DISPLAY_MATH_REGEX.sub(placeholder_display, current_text)

        inline_math_blocks = []
        def placeholder_inline(match):
            inline_math_blocks.append(match.group(1))
            return f"__INLINE_MATH_PLACEHOLDER_{len(inline_math_blocks) - 1}__"

        current_text = INLINE_MATH_REGEX.sub(placeholder_inline, current_text)

        try:
            current_text = LatexNodes2Text(keep_comments=True).latex_to_text(current_text)
        except Exception:
            pass

        for i, raw_content in enumerate(display_math_blocks):
            math_content = raw_content.strip()

            math_content = LATEX_LEFT_RIGHT_REGEX.sub('', math_content)
            math_content = LATEX_ALIGN_ALIGN_REGEX.sub('', math_content)

            matrix_matches = list(MATRIX_ENV_REGEX.finditer(math_content))
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

            replaced_math = MATRIX_ENV_REGEX.sub(matrix_subber, math_content)
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

        for i, line in enumerate(lines):
            if MD_SEP_REGEX.match(line):
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


                    is_known_media_provider = any(pattern.search(url) for pattern in IMAGE_MEDIA_RE_PATTERNS)


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

        matches = []
        for pattern, m_type in MENTION_PATTERNS.items():
            for match in pattern.finditer(text):
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

        return get_keyword_regex(keyword).search(line_lower) is not None

    def _derive_thinking_step(self, thinking_text: str) -> str:
        lines = [line.strip() for line in thinking_text.split('\n') if line.strip()]
        if not lines:
            return "Thinking..."

        for line in reversed(lines):
            line_lower = line.lower()
            clean_line = LEADING_CLEAN_REGEX.sub('', line).strip()

            for keywords, step in self._THINKING_STEP_RULES:
                if any(self._matches_thinking_keyword(line_lower, k) for k in keywords):
                    return step

            match_colon = HEADER_COLON_REGEX.match(clean_line)
            if match_colon:
                header = match_colon.group(1)
                header = STRIP_MARKDOWN_REGEX.sub('', header).strip()

                match_paren = PAREN_HEADER_REGEX.search(header)
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
    async def on_message(self, message, retry_message = None):
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
        author_display_name = message.author.display_name
        if message.guild and not isinstance(message.author, discord.Member):
            member = message.guild.get_member(message.author.id) or await message.guild.fetch_member(message.author.id)
            if member:
                author_display_name = member.display_name
        prompt = f"USER's PROMPT (User's name is {author_display_name}, prompt sent at {message_timestamp} in Discord channel {channel_name}): {prompt.strip()}\nEND OF USER PROMPT"

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

        # Message is for Twilight!, generate response
        if retry_message:
            queue_msg = retry_message
            await queue_msg.edit(content=f"## {self.loading_icon} Just a sec...\n\n", view=None, embed=None)
        else:
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

                linethree = f"\n3. We are in a Discord server called {message.guild.name}, created at {message.guild.created_at.strftime("%d %B %Y, %H:%M UTC")}, and has {message.guild.member_count} members." if message.guild else "3. We are in the user's DMs."
                config_kwargs["system_instruction"] = (
                        system_prompt
                        + f"\n\nSome Extra Info, provided by the system (the word 'system', across all data and metadata provided to you, refers to the Twilight bot code for AI chat):"
                        +  f"\n1. {time_prompt}"
                        + f"\n2. You are running on the model **{current_model}**."
                        + linethree
                )


                gen_config = types.GenerateContentConfig(**config_kwargs)

                current_context = self._prepare_search_context(self.message_history[identifier] + [new_user_message])

                max_retries = 4
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

                            self._active_responses[identifier] = queue_msg.id

                            view = MainResponseView(
                                cog=self,
                                identifier=identifier,
                                message_id=queue_msg.id,
                                cache=self.response_cache,
                                initial_time_str=response_time_str
                            )

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

                await queue_msg.edit(content=f"""Error: Google AI Studio is currently unavailable or encountered a problem. Please try again later.\n> If the error message says "500 Internal Server Error", it is an error on our AI Provider's end i.e. Google AI Studio. Google makes this error message notoriously vague on purpose - it happens seemingly at random, and it's impossible to know what even caused it. Please re-try after a few seconds.\nError Message:\n```{e}```""")
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

            if retry_message and len(self.message_history[identifier]) >= 2:
                self.message_history[identifier].pop()
                self.message_history[identifier].pop()

            self.message_history[identifier].append(
                types.Content(role="user", parts=[types.Part(text=prompt + image_context_text)])
            )

            self.message_history[identifier].append(
                types.Content(role="model", parts=[types.Part(text=self._replace_markdown_separators(full_content))])
            )
            await self._trim_to_tokens(identifier, active_model_name, gen_config, max_tokens=64000)

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
