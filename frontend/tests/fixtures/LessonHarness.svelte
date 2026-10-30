<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import CourseCard from '../../src/lib/components/lessons/CourseCard.svelte';
	import LessonContent from '../../src/lib/components/lessons/LessonContent.svelte';
	import FileEditor from '../../src/lib/components/lessons/FileEditor.svelte';
	import ResourcePolicy from '../../src/lib/components/lessons/ResourcePolicy.svelte';
	import LessonSettings from '../../src/lib/components/lessons/LessonSettings.svelte';
	import type {
		LessonDetail,
		LessonElement,
		ElementKind,
		ScheduleMode
	} from '../../src/lib/lessons';
	let staff = $state(false);
	let upload = $state(false);
	let privateUpload = $state(false);
	let settings = $state(false);
	let mode = $state<ScheduleMode>('inherit');
	let start = $state('2026-10-26');
	let end = $state('2026-10-27');
	let audience = $state<'students' | 'staff'>('students');
	function element(
		id: number,
		kind: ElementKind,
		parent_id: number | null,
		title: string,
		extra: Partial<LessonElement> = {}
	): LessonElement {
		return {
			id,
			kind,
			parent_id,
			title,
			position: id,
			body: '',
			schedule_mode: 'inherit',
			starts_on: null,
			ends_on: null,
			effective_starts_on: null,
			effective_ends_on: null,
			inherited_from: null,
			available: true,
			status: 'available',
			audience: 'students',
			effective_audience: 'students',
			table_rows: 1,
			table_columns: ['Document', 'Vidéo'],
			row_index: null,
			column_index: null,
			file: null,
			...extra
		};
	}
	const root = element(1, 'section', null, 'Chapitre un');
	const file = {
		id: 201,
		original_name: 'Original.pdf',
		extension: 'pdf',
		media_type: 'application/pdf',
		size_bytes: 12,
		sha256: '0'.repeat(64)
	};
	let sample = $state<LessonDetail>({
		id: 1,
		title: 'Algèbre et applications',
		description: 'Explorer les structures et les méthodes de résolution.',
		subject_id: 1,
		subject_name: 'Mathématiques',
		icon: 'calculator',
		color: '#244bc1',
		creator: { id: 99, label: 'Créateur historique', role: 'teacher', can_edit: false },
		responsible: { id: 1, label: 'Camille Martin', role: 'teacher', can_edit: true },
		collaborators: [
			{ id: 2, label: 'Alice Durand', role: 'teacher', can_edit: true },
			{ id: 3, label: 'Zoé Bernard', role: 'kholleur', can_edit: false }
		],
		can_open: true,
		can_edit: true,
		version: 0,
		updated_at: '2026-10-26T12:00:00Z',
		can_view_statistics: false,
		can_manage_collaborators: true,
		can_transfer: true,
		staff_view: false,
		today: '2026-10-26',
		warnings: [],
		promotions: [],
		elements: []
	});
	const lesson = $derived<LessonDetail>({
		...sample,
		staff_view: staff,
		can_edit: staff,
		elements: [
			root,
			element(2, 'text', 1, '', { body: 'Le contenu pédagogique reste toujours visible.' }),
			element(3, 'file', 1, 'Exercices', {
				file,
				schedule_mode: 'from',
				starts_on: '2029-01-01',
				effective_starts_on: '2029-01-01',
				available: false,
				status: 'scheduled'
			}),
			element(4, 'youtube', 1, 'Démonstration', {
				body: staff ? 'https://www.youtube.com/watch?v=abcdefghijk' : '',
				available: false,
				status: 'expired'
			}),
			element(5, 'subsection', 1, 'Approfondissement'),
			element(6, 'text', 5, '', { body: 'Contenu de la sous-section.' }),
			...(staff
				? [
						element(10, 'section', null, 'Équipe seulement', {
							audience: 'staff',
							effective_audience: 'staff'
						}),
						element(11, 'text', 10, '', { body: 'Contenu privé', effective_audience: 'staff' })
					]
				: [])
		]
	});
</script>

<main class="container p-4" style:--lesson-color={sample.color}>
	<div style="max-width: 24rem"><CourseCard lesson={sample} /></div>
	<div class="buttons my-4">
		<button class="button" onclick={() => (staff = !staff)}>Changer de vue</button>
		<button class="button" onclick={() => (settings = true)}>Gérer les collaborateurs</button>
		<button
			class="button"
			onclick={() => {
				privateUpload = false;
				upload = true;
			}}>Déposer un document</button
		>
		<button
			class="button"
			onclick={() => {
				privateUpload = true;
				upload = true;
			}}>Document équipe</button
		>
	</div>
	<LessonContent
		{lesson}
		editing={staff}
		busy={false}
		onedit={() => {}}
		onadd={() => {}}
		onremove={() => {}}
		onmove={() => {}}
		onupdate={() => {}}
	/>
	<ResourcePolicy {mode} {start} {end} {audience} parent={root} kind="text" />
</main>
{#if upload}<FileEditor
		{lesson}
		parent={privateUpload ? { ...root, effective_audience: 'staff' } : root}
		onclose={() => (upload = false)}
		onsaved={() => (upload = false)}
	/>{/if}
{#if settings}<LessonSettings
		lesson={{ ...lesson, can_manage_collaborators: true }}
		onclose={() => (settings = false)}
		onsaved={(updated) => {
			sample = { ...sample, collaborators: updated.collaborators, version: updated.version };
		}}
	/>{/if}
