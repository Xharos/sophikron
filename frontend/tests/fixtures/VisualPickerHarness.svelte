<script lang="ts">
	import VisualPicker from '../../src/lib/components/VisualPicker.svelte';
	import SubjectTag from '../../src/lib/components/SubjectTag.svelte';
	import { lessonIcons, type LessonIcon } from '../../src/lib/lessons';
	let icon = $state<LessonIcon>('book');
	let subjectId = $state(0);
	let disabled = $state(false);
</script>

<form>
	<VisualPicker
		label="Icône"
		bind:value={icon}
		choices={lessonIcons.map((choice) => ({ ...choice, icon: choice.value }))}
	/>
	<SubjectTag subject={{ name: 'Aperçu', icon, color: '#123456' }} />
	<output aria-label="Icône choisie">{icon}</output>
	<VisualPicker
		label="Matière"
		bind:value={subjectId}
		{disabled}
		choices={[
			{ value: 1, label: 'Physique', icon: 'physics', color: '#123456' },
			{ value: 2, label: 'Philosophie', icon: 'philosophy', color: '#f0e080' }
		]}
	/>
	<output aria-label="Matière choisie">{subjectId}</output>
	<button type="button" onclick={() => (disabled = !disabled)}>Désactiver les matières</button>
</form>
