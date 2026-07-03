content = open('outputs/templates/veo3-prompt-library.html', encoding='utf-8').read()
content = content.replace(
    'src="outputs/images/${prompt.category}/2026-05/${prompt.id}.png"',
    'src="generated_images/${prompt.id}.png"'
)
open('outputs/templates/veo3-prompt-library.html', 'w', encoding='utf-8').write(content)
print('Fixed template image path')
print('New img src:', content[content.find('generated_images'):content.find('generated_images')+50])