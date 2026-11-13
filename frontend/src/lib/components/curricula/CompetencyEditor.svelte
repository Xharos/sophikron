<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import ColorPicker from '../ColorPicker.svelte';
	import {
		descendants,
		curriculumRequest,
		type Competency,
		type CompetencyGraph
	} from '#lib/curricula';
	let {
		graph,
		node,
		parentId,
		editable,
		onclose,
		onsaved,
		onchild
	}: {
		graph: CompetencyGraph;
		node?: Competency;
		parentId?: number;
		editable: boolean;
		onclose: () => void;
		onsaved: (graph: CompetencyGraph) => void;
		onchild: (id: number) => void;
	} = $props();
	const original = untrack(() => node);
	let name = $state(original?.name ?? '');
	let nameInput: HTMLInputElement;
	onMount(() => {
		void tick().then(() => nameInput.focus());
	});
	let semester = $state(original?.semester ?? 0);
	let knowledge = $state(original?.knowledge ?? ''),
		comment = $state(original?.comment ?? '');
	let inherit = $state(!original?.color),
		color = $state(original?.color ?? '#4361EE');
	let position = $state(untrack(() => original?.position ?? graph.nodes.length));
	let parents = $state<number[]>(
		untrack(() =>
			original
				? graph.edges.filter((e) => e.child_id === original.id).map((e) => e.parent_id)
				: parentId
					? [parentId]
					: []
		)
	);
	let busy = $state(false),
		message = $state(''),
		confirmDelete = $state(false);
	const initialParent = untrack(() =>
		parentId ? graph.nodes.find((n) => n.id === parentId) : undefined
	);
	const forbidden = $derived(original ? descendants(original.id, graph.edges) : new Set<number>());
	async function submit(remove = false): Promise<void> {
		if (busy || !editable) return;
		busy = true;
		message = '';
		try {
			const updated = await curriculumRequest<CompetencyGraph>(remove ? 'deleteNode' : 'saveNode', {
				curriculum_id: graph.curriculum_id,
				subject_id: graph.subject_id,
				id: original?.id,
				data: remove
					? { expected_version: graph.version }
					: {
							expected_version: graph.version,
							name,
							semester: semester || null,
							knowledge: knowledge || null,
							comment: comment || null,
							color: inherit ? null : color,
							parent_ids: parents,
							position
						}
			});
			onsaved(updated);
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title={original
		? editable
			? 'Modifier la compétence'
			: 'Détail de la compétence'
		: 'Nouvelle compétence'}
	description={initialParent
		? `Sous-compétence de ${initialParent.code ?? ''} ${initialParent.name}`
		: undefined}
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form
		onsubmit={(event) => {
			event.preventDefault();
			void submit();
		}}
	>
		<fieldset disabled={busy || !editable}>
			<div class="field">
				<label class="label" for="competency-name">Nom</label><input
					class="input"
					bind:this={nameInput}
					id="competency-name"
					bind:value={name}
					maxlength="300"
					required
				/>
			</div>
			<details class="mb-3">
				<summary>Semestre</summary>
				<div class="field is-grouped">
					<div class="control">
						<label class="label" for="competency-semester">Échéance d’acquisition</label>
						<div class="select">
							<select id="competency-semester" bind:value={semester}
								><option value={0}>Non précisée</option>{#each [1, 2, 3, 4] as s (s)}<option
										value={s}>Semestre {s}</option
									>{/each}</select
							>
						</div>
					</div>
				</div>
			</details>
			<details open={!editable} class="mb-3">
				<summary>Connaissances et commentaire</summary>
				<div class="field">
					<label class="label" for="competency-knowledge">Connaissances associées</label><textarea
						class="textarea"
						id="competency-knowledge"
						bind:value={knowledge}
						maxlength="12000"
						rows="3"></textarea>
				</div>
				<div class="field">
					<label class="label" for="competency-comment">Commentaire</label><textarea
						class="textarea"
						id="competency-comment"
						bind:value={comment}
						maxlength="12000"
						rows="2"></textarea>
				</div>
			</details>
			<details class="mb-3">
				<summary>Relations</summary>
				<fieldset class="field parent-list">
					<legend class="label">Compétences parentes</legend>
					<p class="help mb-2">
						Aucun parent : compétence racine. Décochez un parent pour détacher cette compétence.
					</p>
					{#each graph.nodes.filter((n) => !forbidden.has(n.id)) as candidate (candidate.id)}<label
							class="checkbox parent-choice"
							><input type="checkbox" bind:group={parents} value={candidate.id} />
							{candidate.code ? `${candidate.code} — ` : ''}{candidate.name}</label
						>{/each}
				</fieldset>
				<div class="field">
					<label class="label" for="competency-position">Ordre d’affichage</label><input
						class="input"
						id="competency-position"
						type="number"
						min="0"
						max="10000"
						step="1"
						bind:value={position}
						required
					/>
				</div>
			</details>
			<details class="mb-3">
				<summary>Présentation</summary>
				<label class="checkbox mb-3"
					><input type="checkbox" bind:checked={inherit} /> Hériter de la couleur de la branche</label
				>
				{#if !inherit}<ColorPicker id="competency-color" bind:value={color} />{/if}
			</details>
		</fieldset>
		{#if editable}
			{#if confirmDelete}<div class="notification is-danger is-light">
					<p>
						Supprimer cette compétence de ses {graph.edges.filter(
							(e) => e.child_id === original?.id
						).length} rattachement(s) ? Ses enfants seront conservés et deviendront des racines s’ils
						n’ont plus de parent.
					</p>
					<button
						type="button"
						class="button is-danger mt-3"
						disabled={busy}
						onclick={() => submit(true)}>Confirmer la suppression</button
					>
				</div>{/if}
		{/if}
		<div class="dialog-actions competency-actions">
			{#if editable}
				{#if original}
					<button
						type="button"
						class="button is-light"
						disabled={busy}
						onclick={() => onchild(original.id)}
						><Icon name="plus" />Ajouter une sous-compétence</button
					><button
						type="button"
						class="button is-danger is-light"
						disabled={busy}
						onclick={() => (confirmDelete = !confirmDelete)}><Icon name="trash" />Supprimer</button
					>
				{/if}{/if}
			<button class="button is-light cancel-action" type="button" disabled={busy} onclick={onclose}
				>{editable ? 'Annuler' : 'Fermer'}</button
			>{#if editable}<button class="button is-primary" class:is-loading={busy} disabled={busy}
					><Icon name="check" />Enregistrer</button
				>{/if}
		</div>
	</form>
</Modal>

<style>
	.competency-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.competency-actions .button {
		font-size: 0.75rem;
		padding-inline: 0.65rem;
	}
	.cancel-action {
		margin-left: auto;
	}
	summary {
		cursor: pointer;
		color: var(--color-primary);
		font-size: 0.85rem;
		padding: 0.5rem 0;
	}
	details[open] summary {
		margin-bottom: 0.6rem;
	}
	.parent-list {
		max-height: 220px;
		overflow: auto;
	}
	.parent-choice {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		padding: 0.4rem 0;
	}
</style>
