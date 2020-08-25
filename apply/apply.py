import asyncio
import string
from difflib import get_close_matches

import discord
from discord.ext import commands

from core import checks
from core.checks import PermissionLevel


def format_channel_name(author):
    name = author.name.lower()
    new_name = (
                       "".join(l for l in name if l not in string.punctuation and l.isprintable()) or "null"
               ) + f"-{author.discriminator}" + "-apply"

    return new_name


def addlines(text):
    return text.replace(r"\n", "\n")


def success(message):
    return discord.Embed(description=message, colour=discord.Colour.green())


class Apply(commands.Cog):
    """Apply."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)

    def error(self, message):
        return discord.Embed(description=message, colour=self.bot.error_color)

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def apply(self, ctx):
        """Start the application process."""
        if await self.db.find_one({'user_id': ctx.author.id, 'inProgress': True}):
            await ctx.send(embed=self.error("You already have an application in progress."))
        else:
            positions = self.db.find({'isPosition': True})
            position_names = []
            for position in await positions.to_list(length=100):
                position_names.append(position["name"])
            if len(position_names) == 0:
                return await ctx.send(embed=self.error("No positions to apply for."))
            config = await self.db.find_one({"_id": "config"})
            category = discord.utils.get(ctx.guild.categories, id=config["main_category"])
            channel = await ctx.guild.create_text_channel(format_channel_name(ctx.author), category=category)
            await channel.set_permissions(ctx.author, read_messages=True, send_messages=True)
            await ctx.send(embed=success(f"Started application in {channel.mention}"))
            await self.db.insert_one({'user_id': ctx.author.id, "inProgress": True, 'channel_id': channel.id})
            position_names_string = "`" + "`, `".join(position_names) + "`"
            embed = discord.Embed(color=self.bot.main_color, title="Choose a position from this list:",
                                  description=position_names_string)
            await channel.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel.id == channel.id

            msg = await self.bot.wait_for('message', check=check)
            while msg.content.lower() not in map(str.lower, position_names):
                close = get_close_matches(msg.content, position_names, 2)
                if close:
                    close = "` or `".join(close)
                    await msg.channel.send(embed=self.error(f"`{msg.content}` not found. Did you mean `{close}`?"))
                else:
                    await msg.channel.send(embed=self.error(f"`{msg.content}` not found."))
                msg = await self.bot.wait_for('message', check=check)
            position = position = await self.db.find_one({"lowered_name": msg.content.lower(), "isPosition": True})
            new_category_id = position["category"]
            new_category = discord.utils.get(ctx.guild.categories, id=new_category_id)
            await channel.edit(category=new_category)
            number_of_questions = len(position["questions"])
            await self.db.update_many({"inProgress": True, "user_id": ctx.author.id},
                                      {"$set": {"questions": position["questions"],
                                                "number_of_questions": number_of_questions,
                                                "position": position["name"]}})
            embed = discord.Embed(colour=self.bot.main_color,
                                  description=f"Use `{ctx.prefix}application next` to move to the next question.")
            await channel.send(embed=embed)
            await asyncio.sleep(2)
            embed = discord.Embed(colour=self.bot.main_color, title=f"Question 1 out of {number_of_questions}",
                                  description=addlines(position["questions"].pop("1")))
            await self.db.update_many({"inProgress": True, "user_id": ctx.author.id},
                                      {"$set": {"questions": position["questions"]}})
            await channel.send(embed=embed)

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def application(self, ctx):
        """Change application stuff."""
        await ctx.send_help(ctx.command)

    @application.command(name="next")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def application_next(self, ctx):
        """Ask the next question."""
        application = await self.db.find_one(
            {"user_id": ctx.author.id, "inProgress": True, "channel_id": ctx.channel.id})
        if application and application.get("questions", None) is not None:
            if len(application["questions"]) == 0:
                embed = discord.Embed(title="Congratulations, you have finished the application!", description="We review the applications every week or so. Please wait for the Head Of Staff to review your application!", color=0x00FF00)
                embed.set_footer(text="Please be patient and dont ping random staff members")
            else:
                number = 1
                while str(number) not in application["questions"]:
                    number += 1
                question = application["questions"].pop(str(number))
                number_of_questions = application["number_of_questions"]
                await self.db.update_many({"inProgress": True, "user_id": ctx.author.id},
                                          {"$set": {"questions": application["questions"]}})
                embed = discord.Embed(colour=self.bot.main_color,
                                      title=f"Question {number} out of {number_of_questions}", description=addlines(question))
            await ctx.message.delete()
        else:
            embed = self.error("You have to be in your application channel to use this command.")
        await ctx.send(embed=embed)

    @application.command(name="close")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def application_close(self, ctx, user: discord.User = None):
        """
        Close an application.
        """
        if user:
            application = await self.db.find_one({"inProgress": True, "user_id": user.id})
            if application:
                await self.db.update_many({"inProgress": True, "user_id": user.id},
                                          {"$set": {"inProgress": False}})
                channel = discord.utils.get(ctx.guild.channels, id=application["channel_id"])
                if channel:
                    await channel.delete()
                await ctx.send(embed=success(f"Closed application of {user.name}#{user.discriminator}."))
            else:
                await ctx.send(embed=self.error("No active application found for this user."))
        else:
            application = await self.db.find_one({"inProgress": True, "channel_id": ctx.channel.id})
            if application:
                await self.db.update_many({"inProgress": True, "channel_id": ctx.channel.id},
                                          {"$set": {"inProgress": False}})
                await ctx.channel.delete()
            else:
                await ctx.send(embed=self.error("No application found for this channel."))

    # @application.command(name="accept")
    # @checks.has_permissions(PermissionLevel.MODERATOR)
    # async def application_accept(self, ctx, user: discord.User):
    #     """Accept a user's application."""
    #     application = await self.db.find_one({"inProgress": True, "user_id": user.id})
    #     if not application:
    #         return await ctx.send(embed=self.error("No active application found for this user."))
    #     config = await self.db.find_one({"_id": "config"})
    #     logchannel = discord.utils.get(ctx.guild.channels, id=config.get("logchannel"))
    #     if logchannel:
    #         await logchannel.send(
    #             embed=success(
    #                 f"{user.mention} has been accepted for `{application.get('position', 'undefined')}` by {ctx.author.mention}."))
    #     await user.send(embed=success(f"You have been accepted for `{application.get('position', 'undefined')}`!"))
    #     channel = discord.utils.get(ctx.guild.channels, id=application["channel_id"])
    #     await channel.send(embed=success(f"Accepted for `{application.get('position', 'undefined')}`!"))
    #
    # @application.command(name="deny")
    # @checks.has_permissions(PermissionLevel.MODERATOR)
    # async def application_deny(self, ctx, user: discord.User):
    #     """Deny a user's application."""
    #     application = await self.db.find_one({"inProgress": True, "user_id": user.id})
    #     if not application:
    #         return await ctx.send(embed=self.error("No active application found for this user."))
    #     config = await self.db.find_one({"_id": "config"})
    #     logchannel = discord.utils.get(ctx.guild.channels, id=config.get("logchannel"))
    #     if logchannel:
    #         await logchannel.send(
    #             embed=self.error(
    #                 f"{user.mention} has been denied for `{application.get('position', 'undefined')}` by {ctx.author.mention}."))
    #     await user.send(embed=self.error(f"You have been denied for `{application.get('position', 'undefined')}`."))
    #     channel = discord.utils.get(ctx.guild.channels, id=application["channel_id"])
    #     await channel.send(embed=self.error(f"Denied for `{application.get('position', 'undefined')}`."))

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def applyconfig(self, ctx):
        """Config some stuff."""
        await ctx.send_help(ctx.command)

    @applyconfig.command(name="maincategory")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def applyconfig_maincategory(self, ctx, category: discord.CategoryChannel):
        """Set the main category where all applications start."""
        await self.db.update_many({"_id": "config"}, {"$set": {"main_category": category.id}}, upsert=True)
        await ctx.send(embed=success(f"Changed `main_category` to `{category.id}`."))

    # @applyconfig.command(name="logchannel")
    # @checks.has_permissions(PermissionLevel.ADMIN)
    # async def applyconfig_logchannel(self, ctx, channel: discord.TextChannel):
    #     """Set the accept and deny log channel."""
    #     await self.db.update_many({"_id": "config"}, {"$set": {"logchannel": channel.id}}, upsert=True)
    #     await ctx.send(embed=success(f"Changed `logchannel` to {channel.mention}."))

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def positions(self, ctx):
        """Change and view positions."""
        await ctx.send_help(ctx.command)

    @positions.command(name="quick")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def positions_quick(self, ctx, name, category: discord.CategoryChannel, *, questions):
        """
        Set a new position quickly. Use help for formatting.
        Use double slashes `//` to separate questions.
        **Example:**
        `[p]positions quick Moderator 515072015103950858 How old are you?//Why do you want to be mod?//What is your prior experience?`
        `[p]positions quick "two wordds" 655046884297015296 TELL US EVERYTHING!`
        `[p]positions quick Admin "name of category" why, tho?//actually, thought, WHY?!?!`
        `[p]positions quick Partner AdminsOnly State coolness level.`
        **Note:**
        Surround position/category names with more than one word with quotes.
        """
        questions = questions.split("//")
        if await self.db.find_one({"isPosition": True, "lowered_name": name.lower()}):
            return await ctx.send(embed=self.error("Already a position with this name."))
        questions_dict = {}
        question_number = 1
        for question in questions:
            questions_dict[str(question_number)] = question
            question_number += 1
        await self.db.insert_one(
            {"isPosition": True, "lowered_name": name.lower(), "name": name, "category": category.id,
             "questions": questions_dict})
        await ctx.send(embed=success(f"Added new position `{name}` with `{len(questions)}` questions."))

    @positions.command(name="all")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def positions_all(self, ctx):
        """See a list of all positions."""
        positions = self.db.find({'isPosition': True})
        position_names = {}
        for position in await positions.to_list(length=100):
            position_names[position["name"]] = len(position["questions"])
        if len(position_names) == 0:
            return await ctx.send(embed=self.error("No positions yet."))
        description = ""
        for name, questions in position_names.items():
            s = "s" if questions > 1 else ""
            description += f"`{name}` - {questions} question{s}\n"
        embed = discord.Embed(title="Positions", description=description, color=self.bot.main_color)
        await ctx.send(embed=embed)

    @positions.command(name="view")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def positions_view(self, ctx, *, position):
        """See an individual position."""
        position = await self.db.find_one({"lowered_name": position.lower(), "isPosition": True})
        if position:
            embed = discord.Embed(title=position["name"], color=self.bot.main_color)
            questions = ""
            for number, question in position["questions"].items():
                questions += f"{number}. `{question}`\n"
            embed.add_field(name="Questions", value=questions)

            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=self.error("No position with that name."))

    @positions.command(name="delete")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def positions_delete(self, ctx, *, position):
        """Delete an individual position."""
        position = await self.db.find_one_and_delete({"lowered_name": position.lower(), "isPosition": True})
        if position:
            await ctx.send(embed=success(f"Deleted `{position['name']}`."))
        else:
            await ctx.send(embed=self.error("No position with that name."))

    # @positions.group(name="edit")
    # @checks.has_permissions(PermissionLevel.ADMIN)
    # async def positions_edit(self, ctx):
    #     """
    #     Edit position stuff.
    #
    #     **Usage:**
    #     `[p]positions edit <what to edit> <name of position> <new value>`
    #
    #     **Example:**
    #     `[p]positions edit name "super mod" not so super mod`
    #     `[p]positions edit category Supporter 515072015103950858`
    #     `[p]positions edit questions SuperStaff Do you like ducks?//Why or why not?`
    #     """
    #     await ctx.send_help(ctx.command)
    #
    # @positions_edit.command(name="name")
    # async def positions_edit_name(self, ctx, position_name, *, new_name):
    #     pass
    #
    # @positions_edit.command(name="category")
    # async def positions_edit_category(self, ctx, position_name, new_category: discord.CategoryChannel):
    #     pass
    #
    # @positions_edit.command(name="questions")
    # async def positions_edit_questions(self, ctx, position_name, questions):
    #     pass


def setup(bot):
    bot.add_cog(Apply(bot))
