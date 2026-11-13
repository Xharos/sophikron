<script lang="ts">
	import { untrack } from 'svelte';
	import Modal from '../Modal.svelte';
	import FileDropzone from '../lessons/FileDropzone.svelte';
	import { competencyFileName, type CompetencyGraph, type CurriculumSubject } from '#lib/curricula';
	let {
		mode,
		curriculumId,
		subjects,
		onclose,
		onsaved
	}: {
		mode: 'import' | 'export';
		curriculumId: number;
		subjects: CurriculumSubject[];
		onclose: () => void;
		onsaved: (graph: CompetencyGraph) => void;
	} = $props();
	let subjectId = $state(untrack(() => subjects[0]?.id ?? 0));
	let source = $state('');
	let selection = 0;
	let selectedFile = $state<File | null>(null);
	let busy = $state(false),
		message = $state(''),
		document = $state<unknown>(null),
		count = $state(0);
	async function selectFile(file: File): Promise<void> {
		const selected = ++selection;
		document = null;
		message = '';
		count = 0;
		selectedFile = file;
		if (
			!file.name.toLowerCase().endsWith('.json') ||
			file.size > 4 * 1024 * 1024 ||
			(file.type && !['application/json', 'text/json'].includes(file.type))
		) {
			message = 'Choisissez un fichier JSON de 4 Mo maximum.';
			return;
		}
		try {
			const text = await file.text();
			if (selected !== selection) return;
			source = text;
			const parsed: unknown = JSON.parse(source);
			if (
				!parsed ||
				typeof parsed !== 'object' ||
				!('format' in parsed) ||
				parsed.format !== 'sophikron.competencies' ||
				!('version' in parsed) ||
				parsed.version !== 1 ||
				!('nodes' in parsed) ||
				!Array.isArray(parsed.nodes) ||
				!parsed.nodes.length ||
				parsed.nodes.length > 2000
			)
				throw new Error();
			document = parsed;
			count = parsed.nodes.length;
		} catch {
			message = 'Fichier JSON invalide ou format non pris en charge.';
		}
	}
	async function transfer(): Promise<void> {
		if (busy || !subjectId) return;
		busy = true;
		message = '';
		try {
			let expected_version: number | undefined;
			if (mode === 'import') {
				const { curriculumRequest } = await import('#lib/curricula');
				expected_version = (
					await curriculumRequest<CompetencyGraph>('graph', {
						curriculum_id: curriculumId,
						subject_id: subjectId
					})
				).version;
			}
			const response = await fetch('/curricula/transfer', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					command: mode,
					curriculum_id: curriculumId,
					subject_id: subjectId,
					expected_version,
					document: mode === 'import' ? source : undefined
				})
			});
			const result = await response.json();
			if (!response.ok) throw new Error(result.message ?? 'La demande a échoué.');
			if (mode === 'import') onsaved(result);
			else {
				const url = URL.createObjectURL(
					new Blob([JSON.stringify(result)], { type: 'application/json' })
				);
				const link = window.document.createElement('a');
				link.href = url;
				link.download = competencyFileName(
					subjects.find((subject) => subject.id === subjectId)?.name ?? 'competences'
				);
				link.click();
				setTimeout(() => URL.revokeObjectURL(url), 1000);
			}
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title={mode === 'import' ? 'Importer des compétences' : 'Exporter des compétences'}
	{onclose}
	{busy}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form
		onsubmit={(event) => {
			event.preventDefault();
			void transfer();
		}}
	>
		<fieldset disabled={busy}>
			<label class="label" for="transfer-subject">Matière</label>
			<div class="select is-fullwidth mb-4">
				<select id="transfer-subject" bind:value={subjectId}
					>{#each subjects as subject (subject.id)}<option value={subject.id}>{subject.name}</option
						>{/each}</select
				>
			</div>
			{#if mode === 'import'}
				<p class="help mb-3">
					Les compétences seront ajoutées à la matière choisie. Les compétences existantes seront
					conservées.
				</p>
				<p class="label">Fichier JSON (4 Mo maximum)</p>
				<FileDropzone
					file={selectedFile}
					accept=".json,application/json"
					disabled={busy}
					onselect={(file) => void selectFile(file)}
				/>
				{#if document}<p class="help">
						{count} compétence(s) à importer. Le serveur vérifiera les champs et les relations avant l’ajout.
					</p>{/if}
			{:else}<p class="help">
					Toutes les compétences de cette matière seront exportées, avec leurs relations, semestres,
					connaissances, commentaires et couleurs.
				</p>{/if}
		</fieldset>
		<div class="dialog-actions">
			<button class="button is-light" type="button" disabled={busy} onclick={onclose}
				>Annuler</button
			><button
				class="button is-primary"
				disabled={busy || !subjectId || (mode === 'import' && !document)}
				>{mode === 'import' ? 'Importer' : 'Télécharger'}</button
			>
		</div>
	</form>
</Modal>
