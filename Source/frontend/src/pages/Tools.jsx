import React from 'react'

// 小工具：常用网站链接（模型社区 / 标签社区 / 学习）
const GROUPS = [
  {
    title: '模型社区',
    links: [
      { name: 'Civitai', desc: '模型下载社区（LoRA / Checkpoint）', url: 'https://civitai.com' },
      { name: 'Hugging Face', desc: '模型 / 数据集 / 脚本', url: 'https://huggingface.co' },
      { name: 'Civitai 教程', desc: '模型发布与使用说明', url: 'https://education.civitai.com' },
    ],
  },
  {
    title: '标签社区',
    links: [
      { name: 'Danbooru', desc: '海量手绘标签参考（tag 库主要来源）', url: 'https://danbooru.donmai.us' },
      { name: 'Gelbooru', desc: '动画/游戏图片标签库', url: 'https://gelbooru.com' },
      { name: 'Rule34', desc: '通用标签图库', url: 'https://rule34.xxx' },
      { name: 'Safebooru', desc: '安全向标签图库', url: 'https://safebooru.org' },
      { name: 'e621', desc: '兽系标签图库', url: 'https://e621.net' },
    ],
  },
  {
    title: '学习 / 工具',
    links: [
      { name: 'LoRA 手册', desc: 'LoRA 训练与使用', url: 'https://huggingface.co/blog/lora' },
      { name: 'Stable Diffusion 教程', desc: '入门 / 参数详解', url: 'https://stability.ai' },
    ],
  },
]

export default function Tools() {
  const openUrl = async (url) => {
    if (window.ftn?.openPath) {
      window.ftn.openPath(url) // 打开 http(s) 会交给系统默认浏览器
    } else {
      window.open(url, '_blank')
    }
  }
  return (
    <div className="px-8 py-6 max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">小工具</h1>
      {GROUPS.map((g) => (
        <div key={g.title} className="mb-6">
          <h2 className="text-sm font-semibold text-txt-secondary mb-3">{g.title}</h2>
          <div className="grid grid-cols-2 gap-3">
            {g.links.map((l) => (
              <button key={l.name} onClick={() => openUrl(l.url)}
                className="rounded-xl border border-base-border bg-base-surface p-5 text-left hover:border-accent/50 transition-colors">
                <div className="font-semibold text-accent mb-1">{l.name}</div>
                <div className="text-sm text-txt-muted">{l.desc}</div>
                <div className="text-[11px] text-txt-muted mt-2 truncate">{l.url}</div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
