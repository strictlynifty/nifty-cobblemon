package xyz.strictlynifty.niftycards.mixin;

import com.cobblemon.mod.common.api.types.ElementalType;
import com.cobblemon.mod.common.entity.pokemon.PokemonEntity;
import com.cobblemon.mod.common.pokemon.Pokemon;
import com.howlite.cobblemoncards.event.BinderSpawnModifier;
import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.player.Player;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Binder conversions keep the Pokemon's shiny, and tell the player they happened.
 *
 * transformPokemon builds the replacement with Species.create(level), so shiny is dropped and
 * re-rolled at base rate. A shiny converted that way leaves no trace: the log records only
 * what it became.
 *
 * At RETURN the `pokemon` parameter is still the original - setPokemon replaced the entity's
 * reference, not the argument - so one injection sees both.
 *
 * Stopgap for Cobblemon Cards 1.0.x. Upstream has since rewritten the binder as a
 * SpawningInfluence that biases spawn weights instead of replacing a spawned Pokemon, which
 * removes the problem at the source. The mixin is therefore optional (required:false): on a
 * version without transformPokemon it simply does not apply, which is the correct outcome.
 * Delete this mod when the cards mod is updated.
 */
@Mixin(BinderSpawnModifier.class)
public abstract class BinderSpawnModifierMixin {

    @Inject(method = "transformPokemon", at = @At("RETURN"), remap = false)
    private static void niftycards$keepShinyAndTell(PokemonEntity entity, Pokemon original,
                                                    ElementalType type, float chance,
                                                    CallbackInfo ci) {
        Pokemon replacement = entity.getPokemon();
        if (replacement == original) {
            return;                          // no candidates of that type; nothing was changed
        }

        boolean wasShiny = original.getShiny();
        if (wasShiny) {
            replacement.setShiny(true);
        }

        Player player = entity.level().getNearestPlayer(entity, 64.0D);
        if (player == null) {
            return;
        }
        Component msg = Component.literal("[Binder] ").withStyle(ChatFormatting.LIGHT_PURPLE)
                .append(Component.literal(original.getSpecies().getName() + " -> "
                                + replacement.getSpecies().getName())
                        .withStyle(ChatFormatting.WHITE))
                .append(Component.literal(String.format(" (%.2f%%)", chance))
                        .withStyle(ChatFormatting.DARK_GRAY));
        if (wasShiny) {
            msg = msg.copy().append(
                    Component.literal(" shiny kept").withStyle(ChatFormatting.GOLD));
        }
        player.displayClientMessage(msg, false);
    }
}
