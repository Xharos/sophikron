<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { lessonCommand, type LessonDetail } from '#lib/lessons';
	import type { Subject } from '#lib/site';
	import type { Page } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import VisualPicker from '../VisualPicker.svelte';
	import SubjectTag from '../SubjectTag.svelte';
	let {
		lesson = null,
		onsaved,
		onclose
	}: {
		lesson?: LessonDetail | null;
		onsaved: (lesson: LessonDetail) => void;
		onclose: () => void;
	} = $props();
	const initialLesson = untrack(() => lesson);
	let title = $state(initialLesson?.title ?? '');
	let description = $state(initialLesson?.description ?? '');
	let subjectId = $state(initialLesson?.subject_id ?? 0);
	let choices = $state<Subject[]>([]);
	let loading = $state(!initialLesson);
	onMount(async () => {
		if (initialLesson) return;
		try {
			let offset = 0,
				total = 1;
			while (offset < total) {
				const response = await fetch(`/lessons/options?resource=subjects&offset=${offset}`, {
					cache: 'no-store'
				});
				if (!response.ok) throw new Error('Les matières n’ont pas pu être chargées.');
				const page = (await response.json()) as Page<Subject>;
				choices.push(...page.items);
				total = page.total;
				offset += 100;
			}
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	});
	let busy = $state(false);
	let message = $state('');
	const initialVersion = initialLesson?.version;
	const dirty = $derived(
		title !== (initialLesson?.title ?? '') ||
			description !== (initialLesson?.description ?? '') ||
			subjectId !== (initialLesson?.subject_id ?? 0)
	);
	function close(): void {
		if (!dirty || window.confirm('Abandonner les modifications du cours ?')) onclose();
	}
	beforeNavigate((navigation) => {
		if (!busy && dirty && !window.confirm('Abandonner les modifications du cours ?'))
			navigation.cancel();
	});
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const data = {
				title,
				description,
				subject_id: subjectId,
				...(lesson ? { expected_version: initialVersion } : {})
			};
			onsaved(
				await lessonCommand<LessonDetail>(lesson ? 'update' : 'create', {
					lessonId: lesson?.id,
					data
				})
			);
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window
	onbeforeunload={(event) => {
		if (dirty && !busy) {
			event.preventDefault();
			event.returnValue = '';
		}
	}}
/>
<Modal
	title={lesson ? 'Les informations du cours' : 'Créer un cours'}
	description="Une identité claire pour votre enseignement."
	{busy}
	onclose={close}
>
	<form onsubmit={save}>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<div class="field">
			<label class="label" for="course-title">Titre du cours</label><input
				id="course-title"
				class="input"
				bind:value={title}
				maxlength="160"
				required
			/>
			<p class="help">Ce titre doit être unique dans l’établissement.</p>
		</div>
		<div class="field">
			<label class="label" for="course-description">Description</label><textarea
				id="course-description"
				class="textarea"
				bind:value={description}
				maxlength="2000"
				rows="3"
				required></textarea>
		</div>
		<div class="field">
			{#if initialLesson}<p class="label">Matière</p>
				<SubjectTag
					subject={{
						name: initialLesson.subject_name,
						icon: initialLesson.icon,
						color: initialLesson.color
					}}
				/>
			{:else if loading}<p role="status">Chargement des matières…</p>
			{:else if !choices.length}<p class="notification is-warning">
					Aucune matière ne vous est affectée. Contactez un administrateur pour créer un cours.
				</p>
			{:else}<VisualPicker
					label="Matière"
					bind:value={subjectId}
					disabled={busy}
					choices={choices.map((choice) => ({
						value: choice.id,
						label: choice.name,
						icon: choice.icon,
						color: choice.color
					}))}
				/>{/if}
			<p class="help">
				L’icône et la couleur sont héritées de la matière. Un administrateur peut réaffecter la
				matière et le responsable.
			</p>
		</div>
		<div class="dialog-actions">
			<button class="button is-light" type="button" disabled={busy} onclick={close}>Annuler</button
			><button
				class="button is-primary"
				class:is-loading={busy}
				disabled={busy || loading || !subjectId}
				type="submit"><Icon name="save" />{lesson ? 'Enregistrer' : 'Créer le cours'}</button
			>
		</div>
	</form>
</Modal>
