<script lang="ts">
	import { untrack } from 'svelte';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import SubjectIdentity from '../SubjectIdentity.svelte';
	import { curriculumRequest, type Curriculum, type CurriculumCatalog } from '#lib/curricula';
	let {
		catalog,
		curriculum,
		onclose,
		onsaved
	}: {
		catalog: CurriculumCatalog;
		curriculum?: Curriculum;
		onclose: () => void;
		onsaved: (curriculum: Curriculum) => void;
	} = $props();
	const original = untrack(() => curriculum);
	let title = $state(original?.title ?? '');
	let description = $state(original?.description ?? '');
	let source = $state(original?.source_url ?? '');
	let subjects = $state<number[]>(original?.subject_ids ?? []);
	let active = $state(original?.is_active ?? true);
	let busy = $state(false),
		message = $state('');
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const saved = await curriculumRequest<Curriculum>('saveCurriculum', {
				id: original?.id,
				data: {
					title,
					description: description || null,
					source_url: source || null,
					subject_ids: subjects,
					is_active: active,
					...(original ? { expected_version: original.version } : {})
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
	title={original ? 'Modifier le référentiel' : 'Nouveau référentiel'}
	description="Le programme des deux années, regroupé par matière."
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form onsubmit={save}>
		<fieldset disabled={busy}>
			<div class="field">
				<label class="label" for="curriculum-title">Nom du référentiel</label><input
					class="input"
					id="curriculum-title"
					bind:value={title}
					maxlength="160"
					placeholder="Programme PTSI / PT"
					required
				/>
			</div>
			<div class="field">
				<label class="label" for="curriculum-description">Description</label><textarea
					class="textarea"
					id="curriculum-description"
					rows="2"
					bind:value={description}
					maxlength="3000"
					placeholder="Le programme des deux années…"></textarea>
			</div>
			<div class="field">
				<label class="label" for="curriculum-source">Lien vers le programme officiel</label><input
					class="input"
					id="curriculum-source"
					type="url"
					bind:value={source}
					maxlength="2000"
					placeholder="https://…"
				/>
				<p class="help">Lien facultatif vers le PDF ou sa page officielle.</p>
			</div>
			<fieldset class="field">
				<legend class="label">Matières du référentiel</legend>
				<div class="subject-choices">
					{#each catalog.subjects.filter((s) => s.is_active || subjects.includes(s.id)) as subject (subject.id)}<label
							class="subject-choice"
							class:selected={subjects.includes(subject.id)}
							><input type="checkbox" bind:group={subjects} value={subject.id} /><SubjectIdentity
								{subject}
							/><span class="choice-check" aria-hidden="true"><Icon name="check" size={13} /></span
							></label
						>{/each}
				</div>
			</fieldset>
			{#if original}<label class="checkbox"
					><input type="checkbox" bind:checked={active} /> Référentiel actif</label
				>{/if}
			<div class="dialog-actions">
				<button class="button is-light" type="button" onclick={onclose}>Annuler</button><button
					class="button is-primary"
					class:is-loading={busy}
					disabled={!subjects.length}><Icon name="check" />Enregistrer</button
				>
			</div>
		</fieldset>
	</form>
</Modal>

<style>
	.subject-choices {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 0.6rem;
	}
	.subject-choice {
		display: flex;
		align-items: center;
		position: relative;
		gap: 0.5rem;
		padding: 0.75rem;
		border: 2px solid var(--color-border);
		border-radius: 0.75rem;
		cursor: pointer;
		background: var(--color-surface);
	}
	.subject-choice.selected {
		border-color: var(--color-primary);
		background: var(--color-soft);
	}
	.subject-choice:focus-within {
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
	}
	.subject-choice input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.choice-check {
		margin-left: auto;
		color: var(--color-primary);
		visibility: hidden;
	}
	.selected .choice-check {
		visibility: visible;
	}
</style>
