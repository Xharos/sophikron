<script lang="ts">
	import { untrack } from 'svelte';
	import { command } from '#lib/dashboard';
	import type { Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	let {
		promotion,
		onclose,
		onsaved
	}: { promotion?: Promotion; onclose: () => void; onsaved: (promotion: Promotion) => void } =
		$props();
	let identifier = $state(untrack(() => promotion?.identifier ?? ''));
	let year = $state(untrack(() => promotion?.year ?? new Date().getFullYear()));
	let color = $state(untrack(() => promotion?.color ?? '#4361EE'));
	let busy = $state(false);
	let message = $state('');
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const saved = await command<Promotion>(promotion ? 'updatePromotion' : 'createPromotion', {
				id: promotion?.id,
				data: { identifier, year, color }
			});
			onsaved(saved);
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title={promotion ? 'Modifier la promotion' : 'Nouvelle promotion'}
	description="Une couleur pour la retrouver au premier regard."
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form onsubmit={save} aria-busy={busy}>
		<div class="field">
			<label class="label" for="promo-name">Identifiant de la promotion</label><input
				id="promo-name"
				class="input"
				bind:value={identifier}
				maxlength="64"
				placeholder="Ex. PTSI"
				required
			/>
		</div>
		<div class="field">
			<label class="label" for="promo-year">Année</label><input
				id="promo-year"
				class="input"
				type="number"
				min="1"
				max="9999"
				step="1"
				bind:value={year}
				required
			/>
		</div>
		<div class="field">
			<label class="label" for="promo-color">Couleur</label>
			<div class="color-picker">
				<input id="promo-color" type="color" bind:value={color} aria-label="Choisir une couleur" />
				<input
					class="input"
					aria-label="Code couleur hexadécimal"
					bind:value={color}
					pattern={'#[0-9A-Fa-f]{6}'}
					maxlength="7"
					required
				/><span
					class="color-preview"
					style={`background: ${/^#[0-9a-f]{6}$/i.test(color) ? color : '#4361EE'}`}
					aria-hidden="true"
				></span>
			</div>
		</div>
		<div class="dialog-actions">
			<button class="button is-light" type="button" onclick={onclose} disabled={busy}
				>Annuler</button
			><button class="button is-primary" type="submit" class:is-loading={busy} disabled={busy}
				><Icon name="check" />Enregistrer</button
			>
		</div>
	</form>
</Modal>
