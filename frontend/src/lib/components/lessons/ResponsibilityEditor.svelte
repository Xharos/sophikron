<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { activeSubjects } from '#lib/dashboard';
	import { lessonCommand, type LessonDetail, type LessonPerson } from '#lib/lessons';
	import type { Subject } from '#lib/site';
	import Modal from '../Modal.svelte';
	let {
		lesson,
		onsaved,
		onclose
	}: { lesson: LessonDetail; onsaved: (lesson: LessonDetail) => void; onclose: () => void } =
		$props();
	const snapshot = untrack(() => ({ version: lesson.version, subject: lesson.subject_id }));
	let subjects = $state<Subject[]>([]),
		subjectId = $state(snapshot.subject),
		query = $state(''),
		selected = $state<LessonPerson | null>(null);
	let candidates = $state<LessonPerson[]>([]),
		busy = $state(false),
		loading = $state(true),
		message = $state(''),
		searched = $state(false),
		confirmed = $state(false);
	onMount(async () => {
		try {
			subjects = await activeSubjects();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	});
	async function search(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		selected = null;
		confirmed = false;
		try {
			const params = new URLSearchParams({
				resource: 'responsible',
				lessonId: String(lesson.id),
				subjectId: String(subjectId),
				q: query
			});
			const response = await fetch(`/lessons/options?${params}`, { cache: 'no-store' });
			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.message ?? error.detail ?? 'Recherche indisponible.');
			}
			candidates = (await response.json()) as LessonPerson[];
			searched = true;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function save(): Promise<void> {
		if (!selected || !confirmed) return;
		busy = true;
		message = '';
		try {
			onsaved(
				await lessonCommand<LessonDetail>('transfer', {
					lessonId: lesson.id,
					data: {
						expected_version: snapshot.version,
						responsible_id: selected.id,
						subject_id: subjectId
					}
				})
			);
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal title="Réaffecter le responsable principal" {busy} {onclose}>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<p class="mb-4">
		Responsable actuel : <strong>{lesson.responsible.label}</strong>. L’auteur d’origine, {lesson
			.creator.label}, restera conservé.
	</p>
	{#if loading}<p role="status">Chargement des matières…</p>{:else}
		<div class="field">
			<label class="label" for="responsibility-subject">Matière du cours</label>
			<div class="select is-fullwidth">
				<select
					id="responsibility-subject"
					bind:value={subjectId}
					disabled={busy}
					onchange={() => {
						selected = null;
						candidates = [];
						searched = false;
						confirmed = false;
					}}
					>{#each subjects as subject (subject.id)}<option value={subject.id}>{subject.name}</option
						>{/each}</select
				>
			</div>
		</div>
		<form onsubmit={search}>
			<label class="label" for="responsible-query"
				>Rechercher un enseignant possédant cette matière</label
			>
			<div class="field has-addons">
				<div class="control is-expanded">
					<input
						id="responsible-query"
						class="input"
						type="search"
						bind:value={query}
						minlength="2"
						maxlength="100"
						required
					/>
				</div>
				<div class="control">
					<button class="button is-light" disabled={busy}>Rechercher</button>
				</div>
			</div>
		</form>
		{#each candidates as person (person.id)}<label class="candidate"
				><input
					type="radio"
					name="responsible"
					checked={selected?.id === person.id}
					disabled={busy}
					onchange={() => {
						selected = person;
						confirmed = false;
					}}
				/>
				{person.label}</label
			>{/each}
		{#if searched && !candidates.length}<p class="muted">
				Aucun enseignant actif possédant cette matière trouvé.
			</p>{/if}
		{#if selected}<div class="notification is-warning is-light mt-4">
				<p>
					{selected.label} deviendra responsable. L’ancien responsable perdra ses droits liés à cette
					fonction. Si la matière change, l’icône et la couleur suivront et les collaborateurs enseignants
					sans cette matière seront retirés. Les khôlleurs conserveront leur lecture seule.
				</p>
				<label class="checkbox mt-3"
					><input type="checkbox" bind:checked={confirmed} /> Confirmer cette réaffectation</label
				>
			</div>{/if}
		<div class="dialog-actions">
			<button class="button is-light" disabled={busy} onclick={onclose}>Annuler</button><button
				class="button is-primary"
				disabled={busy || !selected || !confirmed}
				class:is-loading={busy}
				onclick={save}>Enregistrer le responsable</button
			>
		</div>
	{/if}
</Modal>

<style>
	.candidate {
		display: block;
		padding: 0.7rem 0;
	}
</style>
