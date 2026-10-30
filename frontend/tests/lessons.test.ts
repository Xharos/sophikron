import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	colorForeground,
	formattedText,
	formattedBlocks,
	documentLabel,
	periodLabel,
	lessonTeam,
	type LessonPerson
} from '../src/lib/lessons.ts';

test('course teams group the responsible teacher and collaborators without duplicates', () => {
	const person = (id: number, label: string, role: LessonPerson['role']): LessonPerson => ({
		id,
		label,
		role,
		can_edit: role === 'teacher'
	});
	const responsible = person(1, 'Zoé Responsable', 'teacher');
	const team = lessonTeam({
		responsible,
		collaborators: [
			person(2, 'Zoé Collègue', 'teacher'),
			person(3, 'Alice Collègue', 'teacher'),
			person(4, 'Khôlleur', 'kholleur'),
			responsible
		]
	});
	assert.deepEqual(
		team.teachers.map((member) => member.id),
		[1, 3, 2]
	);
	assert.deepEqual(
		team.kholleurs.map((member) => member.id),
		[4]
	);
});

test('document labels hide the actual extension and preserve author titles and internal dots', () => {
	for (const extension of ['pdf', 'docx', 'xlsx', 'jpg', 'jpeg', 'png', 'zip', 'py']) {
		assert.equal(documentLabel(`Chapitre.1.${extension}`, extension), 'Chapitre.1');
		assert.equal(documentLabel(`Chapitre.${extension.toUpperCase()}`, extension), 'Chapitre');
		assert.equal(documentLabel('Un titre pédagogique', extension), 'Un titre pédagogique');
	}
	assert.equal(documentLabel('Version 1.2', 'pdf'), 'Version 1.2');
	assert.equal(documentLabel('.pdf', 'pdf'), '.pdf');
});

test('section headings preserve multiline formatting and leave HTML as literal text', () => {
	const blocks = formattedBlocks(
		'# **Section**\n## ==Sous-section==\n**première\nseconde**\n<script>alert(1)</script>'
	);
	assert.equal(blocks[0].level, 1);
	assert.equal(blocks[0].parts[0].text, 'Section');
	assert.ok(blocks[0].parts[0].bold);
	assert.equal(blocks[1].level, 2);
	assert.ok(blocks[1].parts[0].colored);
	assert.ok(blocks[2].parts[0].bold && blocks[3].parts[0].bold);
	assert.equal(blocks[4].parts[0].text, '<script>alert(1)</script>');
	assert.equal(formattedBlocks('### Littéral')[0].level, 0);
});

test('inline effects combine in either wrapping order without interpreting HTML', () => {
	for (const value of ['==***mot***==', '***==mot==***', '**==*mot*==**']) {
		assert.deepEqual(formattedText(value), [
			{ text: 'mot', bold: true, italic: true, colored: true }
		]);
	}
	assert.deepEqual(
		formattedText('**gras** *italique* ==coloré==').filter((part) => part.text.trim()),
		[
			{ text: 'gras', bold: true, italic: false, colored: false },
			{ text: 'italique', bold: false, italic: true, colored: false },
			{ text: 'coloré', bold: false, italic: false, colored: true }
		]
	);
	const hostile = '<script>alert(1)</script><img src=x onerror=alert(1)>';
	assert.deepEqual(formattedText(hostile), [
		{ text: hostile, bold: false, italic: false, colored: false }
	]);
	assert.equal(
		formattedText('Texte **incomplet')
			.map((part) => part.text)
			.join(''),
		'Texte **incomplet'
	);
});

test('course colors remain readable and date labels preserve calendar dates', () => {
	assert.equal(colorForeground('#FFFFFF'), '#000000');
	assert.equal(colorForeground('#000000'), '#ffffff');
	assert.equal(periodLabel(null, null), 'Toute l’année');
	assert.match(periodLabel('2026-09-01', null), /À partir du 1 sept/);
	assert.match(periodLabel('2026-09-01', '2027-08-31'), /31 août 2027/);
});
