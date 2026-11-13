<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { curriculumRequest, type Curriculum, type CurriculumCatalog } from '#lib/curricula';
	import { command } from '#lib/dashboard';
	import type { Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import ColorPicker from '../ColorPicker.svelte';
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
	let curriculumId = $state(untrack(() => promotion?.curriculum_id ?? 0));
	let curricula = $state<Curriculum[]>([]);
	let curriculumError = $state('');
	onMount(() => {
		curriculumRequest<CurriculumCatalog>('catalog')
			.then((catalog) => (curricula = catalog.curricula))
			.catch(
				() =>
					(curriculumError =
						'Les référentiels sont indisponibles. Le rattachement actuel sera conservé.')
			);
	});
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const saved = await command<Promotion>(promotion ? 'updatePromotion' : 'createPromotion', {
				id: promotion?.id,
				data: {
					identifier,
					year,
					color,
					...(!curriculumError ? { curriculum_id: curriculumId || null } : {})
				}
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
		<ColorPicker id="promo-color" bind:value={color} disabled={busy} />
		<div class="field">
			<label class="label" for="promo-curriculum">Référentiel facultatif</label>
			<div class="select is-fullwidth">
				<select id="promo-curriculum" bind:value={curriculumId} disabled={busy || !!curriculumError}
					><option value={0}>Aucun référentiel</option
					>{#each curricula.filter((t) => t.is_active || t.id === curriculumId) as curriculum (curriculum.id)}<option
							value={curriculum.id}
							>{curriculum.title}{curriculum.is_active ? '' : ' · Archivé'}</option
						>{/each}</select
				>
			</div>
			{#if curriculumError}<p class="help">{curriculumError}</p>{/if}
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
