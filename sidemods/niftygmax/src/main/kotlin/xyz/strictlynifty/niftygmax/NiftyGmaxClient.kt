package xyz.strictlynifty.niftygmax

import com.cobblemon.mod.common.api.Priority
import com.cobblemon.mod.common.api.events.CobblemonEvents
import com.cobblemon.mod.common.client.CobblemonClient
import com.cobblemon.mod.common.client.gui.interact.wheel.InteractWheelOption
import net.fabricmc.api.ClientModInitializer
import com.cobblemon.mod.common.entity.pokemon.PokemonEntity
import net.minecraft.client.Minecraft
import net.minecraft.resources.ResourceLocation
import java.util.UUID
import org.joml.Vector3f
import org.slf4j.LoggerFactory

/**
 * Adds a Gigantamax button to Cobblemon's interaction wheel, beside Mega Evolve.
 *
 * Mega Showdown gates the G-max form behind a battle AND a Power Spot, so a form the player
 * earned with a Max Soup is only visible for a few turns. The server can already show it
 * anywhere - `/trigger gmax set <slot>` toggles it, gated on GmaxFactor - but a chat command
 * nobody can discover is not a feature. This puts it where Mega Evolve already is.
 *
 * This is a SIDEMOD and contains no Mega Showdown code. Its licence (v2.1 §1.3) permits
 * sidemods - addons that interact with the mod without including substantial portions of it -
 * to be built and shared without asking, whereas a modified build of the mod itself would need
 * written permission before being given to anyone. Everything here talks to Cobblemon's public
 * API and then issues a server command. The one Mega Showdown thing referenced is its icon, by
 * ResourceLocation, so the file is read from its jar at runtime and never copied into ours.
 *
 * Client-only by design. All eligibility - has the species a G-max model, was it actually fed
 * a Max Soup - stays server-side in gmaxwatch.py, because GmaxFactor lives in the party-store
 * NBT and is not something the client can be trusted to judge. The button is always offered;
 * the server refuses with a reason if it does not qualify.
 */
object NiftyGmaxClient : ClientModInitializer {

    private val LOG = LoggerFactory.getLogger("niftygmax")

    /** Mega Showdown's own G-max icon, already 32x32 like the two existing wheel icons. */
    private val ICON: ResourceLocation =
        ResourceLocation.fromNamespaceAndPath("mega_showdown", "textures/gui/summary/gmax.png")

    /** Dynamax pink, so the button reads as belonging with the G-max UI. */
    private val COLOUR = Vector3f(0.93f, 0.26f, 0.60f)

    override fun onInitializeClient() {
        CobblemonEvents.POKEMON_INTERACTION_GUI_CREATION.subscribe(Priority.NORMAL) { event ->
            try {
                addGmaxOption(event)
            } catch (e: Throwable) {
                // Never let this break the wheel: without the catch, a change in Cobblemon's
                // API would stop the player interacting with their Pokemon at all.
                LOG.error("could not add the Gigantamax wheel option", e)
            }
            Unit
        }
        LOG.info("Gigantamax wheel option registered")
    }

    private fun addGmaxOption(
        event: com.cobblemon.mod.common.api.events.pokemon.interaction.PokemonInteractionGUICreationEvent
    ) {
        val slot = partySlotOf(event.pokemonID) ?: return   // not in the party: nothing to toggle

        event.addFillingOption(
            InteractWheelOption(
                iconResource = ICON,
                secondaryIconResource = null,
                enabled = true,
                tooltipText = "niftygmax.ui.gigantamax",
                colour = { COLOUR },
                onPress = {
                    // Same command the player could type. The server decides whether it is
                    // allowed and says so; this is only a nicer way to reach it.
                    Minecraft.getInstance().player?.connection?.sendCommand("trigger gmax set $slot")
                    Minecraft.getInstance().setScreen(null)
                    Unit
                }
            )
        )
    }

    /**
     * 1-based party slot for the Pokemon behind this interaction, or null if it is not in the
     * player's party.
     *
     * The event's `pokemonID` is the world ENTITY's uuid, NOT the Pokemon's - the two differ,
     * and passing it straight to ClientParty.getPosition always returns -1. Mega Showdown
     * never trips over this because it forwards the id to the server and resolves it there.
     * So: find the entity, take the Pokemon it is carrying, and look THAT up.
     */
    private fun partySlotOf(entityId: UUID): Int? {
        val level = Minecraft.getInstance().level ?: return null
        val entity = level.entitiesForRendering()
            .firstOrNull { it.uuid == entityId } as? PokemonEntity ?: return null
        val position = CobblemonClient.storage.party.getPosition(entity.pokemon.uuid)
        return if (position >= 0) position + 1 else null
    }
}
