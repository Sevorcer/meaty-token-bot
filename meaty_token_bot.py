# Use the attached file at /mnt/data/meaty_token_bot_fixed.py as your drop-in replacement.
# It already includes the /player OVR fallback fix and /team + /roster pagination buttons.
#
# Add the two command blocks below into that file if you only want the new features.
#
# 1) Casino leaderboard (keep existing /leaderboard unchanged)
# 2) Role-based token award command

@bot.tree.command(name="casinoleaderboard", description="Show casino leaders by highest win percentage (minimum 10 casino games).")
async def casinoleaderboard(interaction: discord.Interaction):
    with TOKEN_DB.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                user_id,
                username,
                casino_wins,
                casino_losses,
                (casino_wins + casino_losses) AS total_games,
                CASE
                    WHEN (casino_wins + casino_losses) > 0
                    THEN CAST(casino_wins AS REAL) / (casino_wins + casino_losses)
                    ELSE 0
                END AS win_pct
            FROM users
            WHERE (casino_wins + casino_losses) >= 10
            ORDER BY win_pct DESC, casino_wins DESC, total_games DESC, username ASC
            """
        )
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No users qualify yet. A minimum of **10 total casino games** is required."
        )
        return

    lines = []
    for idx, row in enumerate(rows, start=1):
        win_pct = (row["win_pct"] or 0) * 100
        total_games = row["total_games"] or 0
        lines.append(
            f"**{idx}.** <@{row['user_id']}> — **{win_pct:.1f}%** win rate | **{row['casino_wins']}** wins | **{total_games}** games"
        )

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > 3800:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))

    await interaction.response.send_message(
        embed=build_embed(
            "🎰 Casino Leaderboard",
            chunks[0] + "\n\n*Minimum 10 total casino games required.*",
            0xFEE75C,
        )
    )

    for page_num, chunk in enumerate(chunks[1:], start=2):
        await interaction.followup.send(
            embed=build_embed(
                f"🎰 Casino Leaderboard (Page {page_num})",
                chunk,
                0xFEE75C,
            )
        )


@bot.tree.command(name="addroletokens", description="Admin: add tokens to everyone with a specific role.")
@admin_only()
@app_commands.describe(
    role="Role to reward",
    amount="Amount to give each member with that role",
    reason="Reason shown in the ledger",
)
async def addroletokens(interaction: discord.Interaction, role: discord.Role, amount: float, reason: str):
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return

    members = [member for member in role.members if not member.bot]

    if not members:
        await interaction.response.send_message(
            f"No non-bot members were found with the role **{role.name}**.",
            ephemeral=True,
        )
        return

    for member in members:
        TOKEN_DB.add_tokens(member, amount, reason, "admin")

    await interaction.response.send_message(
        f"✅ Added **{fmt_tokens(amount)}** tokens to **{len(members)}** members with the role {role.mention}.\n"
        f"**Reason:** {reason}"
    )

    await send_log_message(
        f"💰 ADMIN: {interaction.user.mention} added **{fmt_tokens(amount)}** tokens to "
        f"**{len(members)}** members with the role **{role.name}**. Reason: **{reason}**"
    )
