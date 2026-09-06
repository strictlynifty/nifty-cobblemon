package xyz.strictlynifty.niftygmaxserver;

import com.cobblemon.mod.common.Cobblemon;
import com.cobblemon.mod.common.api.storage.party.PlayerPartyStore;
import com.cobblemon.mod.common.pokemon.Pokemon;
import com.github.yajatkaul.mega_showdown.api.codec.Effect;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.Commands;
import net.minecraft.commands.arguments.EntityArgument;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.Optional;

/**
 * `/niftygmax revert <player> <slot>` — turns one Pokémon's Gigantamax display back off.
 *
 * Nothing else can. The model follows the `gmax` aspect, which comes from Cobblemon's
 * `dynamax_form` species feature; `FormId` is a different field and changing it does nothing
 * visible. `dynamax_form` is a choice feature whose default "none" is not among its choices,
 * so `pokeedit dynamax_form=none` is rejected by the validator while still printing
 * "Edited ...". `unaspect=gmax` and `gmax=false` do nothing either.
 *
 * Mega Showdown's own `/msd hard_reset` clears it, but walks the whole party AND PC, reverts
 * every Mega too, and wipes GmaxFactor so players must re-feed Max Soups. This makes the same
 * call it makes internally, for a single Pokémon:
 *
 *     Effect.getEffect("mega_showdown:dynamax")
 *           .revertEffects(pokemon, List.of("dynamax_form=none"), Optional.empty(), null);
 *
 * Deliberately a separate mod from niftygmax so the client jar players already have does not
 * need reissuing. Server-side only; nobody but the server installs this.
 */
public class NiftyGmaxServer implements ModInitializer {

    private static final Logger LOG = LoggerFactory.getLogger("niftygmaxserver");
    private static final String DYNAMAX_EFFECT = "mega_showdown:dynamax";

    @Override
    public void onInitialize() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registry, env) ->
                dispatcher.register(Commands.literal("niftygmax")
                        .requires(src -> src.hasPermission(2))
                        .then(Commands.literal("revert")
                                .then(Commands.argument("player", EntityArgument.player())
                                        .then(Commands.argument("slot", IntegerArgumentType.integer(1, 6))
                                                .executes(ctx -> revert(
                                                        ctx.getSource(),
                                                        EntityArgument.getPlayer(ctx, "player"),
                                                        IntegerArgumentType.getInteger(ctx, "slot"))))))));
        LOG.info("/niftygmax revert registered");
    }

    private static int revert(net.minecraft.commands.CommandSourceStack src,
                              ServerPlayer player, int slot) {
        PlayerPartyStore party = Cobblemon.INSTANCE.getStorage().getParty(player);
        Pokemon pokemon = party.get(slot - 1);
        if (pokemon == null) {
            src.sendFailure(Component.literal("Nothing in party slot " + slot));
            return 0;
        }
        if (!pokemon.getAspects().contains("gmax")) {
            // Same test hard_reset uses to decide whether a Pokemon needs reverting.
            src.sendSuccess(() -> Component.literal(
                    pokemon.getSpecies().getName() + " is not showing a Gigantamax form"), false);
            return 0;
        }

        try {
            Effect effect = Effect.getEffect(DYNAMAX_EFFECT);
            if (effect == null) {
                src.sendFailure(Component.literal("Mega Showdown has no " + DYNAMAX_EFFECT + " effect"));
                return 0;
            }
            effect.revertEffects(pokemon, List.of("dynamax_form=none"), Optional.empty(), null);
        } catch (Throwable t) {
            // Mega Showdown absent, or its API moved. Fail loudly to the caller rather than
            // reporting a success that did nothing - that mistake is the reason this exists.
            LOG.error("revert failed for {} slot {}", player.getGameProfile().getName(), slot, t);
            src.sendFailure(Component.literal("Revert failed: " + t));
            return 0;
        }

        boolean cleared = !pokemon.getAspects().contains("gmax");
        if (cleared) {
            src.sendSuccess(() -> Component.literal(
                    "Reverted " + pokemon.getSpecies().getName()), false);
            LOG.info("reverted {} slot {} ({})",
                    player.getGameProfile().getName(), slot, pokemon.getSpecies().getName());
            return 1;
        }
        src.sendFailure(Component.literal(
                "Called the revert but " + pokemon.getSpecies().getName() + " still has the gmax aspect"));
        return 0;
    }
}
