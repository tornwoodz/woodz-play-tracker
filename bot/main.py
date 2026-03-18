@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.lower().strip()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    def detect_result(text: str) -> Optional[str]:
        exact = text.strip()

        if exact in {"win", "w", "cash", "cashed", "hit"}:
            return "win"
        if exact in {"loss", "l", "lost", "miss", "missed"}:
            return "loss"
        if exact in {"push", "p"}:
            return "push"

        if "as a win" in text or "grade win" in text or "mark win" in text or "this hit" in text or "cash it" in text:
            return "win"
        if "as a loss" in text or "grade loss" in text or "mark loss" in text or "it lost" in text or "missed" in text:
            return "loss"
        if "as a push" in text or "grade push" in text or "mark push" in text:
            return "push"

        return None

    result = detect_result(content)

    # --- reply-to-pick flow for bot-created picks ---
    if message.reference and result in {"win", "loss", "push"}:
        if data.get("owner_id") and not is_owner_user(message.author.id):
            await bot.process_commands(message)
            return

        try:
            referenced = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            await bot.process_commands(message)
            return

        # Existing mapped bot pick
        pick_id = data["message_pick_map"].get(str(referenced.id))
        if pick_id:
            pick = find_pick_by_id(int(pick_id))
            if pick:
                ok, msg = apply_grade_to_pick(pick, result, message.author.id)
                if ok:
                    await disable_pick_buttons_for_message(
                        message.channel,
                        int(referenced.id),
                        pick,
                    )
                    await message.channel.send(msg)
                    if message.guild:
                        await post_recap_if_configured(message.guild)
                else:
                    await message.channel.send(msg)

                await bot.process_commands(message)
                return

    # --- NEW: reply-to-any-graphic flow when bot is mentioned ---
    if message.reference and bot_mentioned:
        if data.get("owner_id") and not is_owner_user(message.author.id):
            await bot.process_commands(message)
            return

        try:
            referenced = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            await message.channel.send("Could not find the message you replied to.")
            await bot.process_commands(message)
            return

        has_graphic = (
            len(referenced.attachments) > 0
            or len(referenced.embeds) > 0
        )

        if not has_graphic:
            await bot.process_commands(message)
            return

        # If user says "grade this" with mention, show buttons
        if "grade this" in content and result is None:
            temp_pick = {
                "id": len(data["picks"]) + len(data["graded_history"]) + 1,
                "bet": f"Manual graphic reply from message {referenced.id}",
                "units": 1.0,
                "odds": -110,
                "status": "pending",
                "created_by": message.author.id,
                "created_at": utc_now_iso(),
                "graded_at": None,
                "graded_by": None,
                "result": None,
                "profit_units": 0.0,
            }

            data["picks"].append(temp_pick)
            save_data(data)

            embed = build_pick_embed(temp_pick)
            sent = await message.channel.send(
                f"Reply-based manual pick created from your graphic.",
                embed=embed,
                view=GradeView(temp_pick["id"]),
            )

            data["message_pick_map"][str(sent.id)] = temp_pick["id"]
            save_data(data)

            await bot.process_commands(message)
            return

        # If user directly says @bot ... as a win/loss/push
        if result in {"win", "loss", "push"}:
            manual_pick = {
                "id": len(data["picks"]) + len(data["graded_history"]) + 1,
                "bet": f"Manual graphic reply from message {referenced.id}",
                "units": 1.0,
                "odds": -110,
                "status": "pending",
                "created_by": message.author.id,
                "created_at": utc_now_iso(),
                "graded_at": None,
                "graded_by": None,
                "result": None,
                "profit_units": 0.0,
            }

            data["picks"].append(manual_pick)
            save_data(data)

            ok, msg = apply_grade_to_pick(manual_pick, result, message.author.id)
            await message.channel.send(msg)

            if ok and message.guild:
                await post_recap_if_configured(message.guild)

            await bot.process_commands(message)
            return

    await bot.process_commands(message)
