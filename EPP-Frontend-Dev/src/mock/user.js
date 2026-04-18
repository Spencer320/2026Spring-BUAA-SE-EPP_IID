import Mock from 'mockjs'

Mock.mock(/\/paper\/annotations\?paper_id=.*/, 'get', {
  'data': [
    {
      'id': '1',
      'position': {
        'x': 149,
        'y': 172.0000114440918,
        'width': 262,
        'height': 317,
        'pageNum': 1
      },
      'content': '有道理',
      'date': '2024-12-08 09:45:30',
      'author_name': '123',
      'author_avatar': '/static/favicon.png',
      'liked': false,
      'comment_count': 1
    }
  ],
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/paper\/annotation\?paper_id=.*/, 'put', {
  'data': {
    'id': '1',
    'date': '2024-12-08 09:45:30'
  },
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comments\?annotation_id=.*/, 'get', {
  'data': [
    {
      'id': '2',
      'date': '2024-12-08 09:45:30',
      'author_name': 'dafasdf',
      'author_avatar': '/static/favicon.png',
      'content': 'adsfsdfsadf',
      'liked': false,
      'sub_comment_count': 1
    }
  ],
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comment\/subcomments\?annotation_id=\w+&comment_id=\w+/, 'get', {
  'data': [
    {
      'id': '3',
      'date': '2024-12-08 09:45:30',
      'author_name': 'asdfadsf',
      'author_avatar': '/static/favicon.png',
      'content': 'adsfsdafas',
      'liked': false
    }
  ],
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comment\?annotation_id=\w+/, 'put', {
  'data': {
    'id': '5',
    'date': '2024-12-08 09:45:30',
    'message': 'optional<str>',
    'error': 'optional<str>'
  },
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comments\/subcomment\?annotation_id=\w+&comment_id=\w+/, 'put', {
  'data': {
    'id': '6',
    'date': '2024-12-08 09:45:30',
    'message': 'optional<str>',
    'error': 'optional<str>'
  },
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/like\/toggle\?annotation_id=\w+/, 'post', {
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comments\/like\/toggle\?comment_id=\w+&comment_level=\d+/, 'post', {
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/annotation\/comments\/like\/toggle\?comment_id=\w+&comment_level=\w+/, 'post', {
  'message': 'optional<str>',
  'error': 'optional<str>'
})

Mock.mock(/\/summary\/generateSummaryReport/, 'post', {
  message: '生成成功',
  error: null,
  data: {
    report_id: '1'
  }
})

Mock.mock(/\/v2\/summary\/status\?report_id=\w+/, 'get', {
  message: '查询成功',
  error: null,
  data: {
    type: 'response',
    content: `
近年来，随着人工智能技术的迅猛发展，深度学习、图神经网络和自然语言处理等领域取得了重要突破。尤其是在医疗诊断、金融预测与自动驾驶等应用场景中，AI模型的实际效能不断提升。
尽管如此，模型的可解释性、安全性以及能耗问题仍是未来研究的重要方向，亟需更多创新性方法予以解决。
`
  }
})

Mock.mock(/\/v2\/summary\/response\?report_id=\w+/, 'post', {
  message: '获取成功',
  error: null,
  data: {
  }
})

// 用户登录
Mock.mock('/api/login', 'post', {
  message: 'Login successful',
  expired_time: '2025-05-26T00:00:00',
  ULogin_legal: true,
  user_id: 1,
  username: 'test_user',
  avatar: 'https://randomuser.me/api/portraits/women/2.jpg'
})

// 用户注册
Mock.mock('/api/sign', 'post', {
  user_id: 2,
  username: 'new_user',
  avatar: 'https://avatars.githubusercontent.com/u/583231?v=4'
})

// 管理员登出
Mock.mock('/api/managerLogout', 'get', {
  message: '管理员登出成功'
})

// 用户退出登录
Mock.mock('/api/logout', 'get', {
  message: '用户登出成功'
})

// 管理员登录
Mock.mock('/api/managerLogin', 'post', {
  message: '管理员登录成功',
  MLogin_legal: true
})

// 登录状态测试
Mock.mock('/api/testLogin', 'get', {})

// 论文点赞/取消点赞
Mock.mock('/api/userLikePaper', 'post', {
  message: '操作成功：已点赞'
})

// 论文评分
Mock.mock('/api/userScoring', 'post', {
  message: '评分成功'
})

// 论文收藏/取消收藏
Mock.mock('/api/collectPaper', 'post', {
  message: '操作成功：已收藏'
})

// 论文评论
Mock.mock('/api/commentPaper', 'post', {
  message: '评论成功',
  is_success: true
})

// 批量下载
Mock.mock('/api/batchDownload', 'post', {
  message: '批量下载成功',
  zip_url: 'https://www.learningcontainer.com/wp-content/uploads/2020/05/sample-zip-file.zip',
  is_success: true
})

// 举报评论
Mock.mock('/api/reportComment', 'post', {
  message: '举报成功',
  is_success: true
})

// 获取论文详情
Mock.mock(RegExp('/api/getPaperInfo.*'), 'get', {
  abstract: '这是一篇关于人工智能在医学图像分析中应用的研究论文。',
  authors: '张三，李四，王五',
  citation_count: 42,
  collect_count: 10,
  comment_count: 5,
  download_count: 120,
  journal: '人工智能期刊',
  like_count: 35,
  original_url: 'https://arxiv.org/pdf/2403.00123.pdf',
  paper_id: 'paper001',
  publication_date: '2024-09-15',
  read_count: 200,
  score: 4.6,
  score_count: 18,
  title: '基于深度学习的医学图像分析方法研究'
})

// 获取术语表列表
Mock.mock(/\/api\/translate\/glossaries/, 'get', (options) => {
  return {
    message: '获取术语表成功',
    data: [
      {
        id: 'glossary001',
        name: 'NLP 术语表',
        recomend: true
      },
      {
        id: 'glossary002',
        name: '医学图像术语表',
        recomend: false
      },
      {
        id: 'glossary003',
        name: '计算机视觉术语表',
        recomend: true
      }
    ]
  }
})

// 获取术语表详情（通过查询参数 glossary_id）
Mock.mock(/\/api\/translate\/glossary/, 'get', (options) => {
  const url = new URL('http://dummy.com' + options.url)
  const glossaryId = url.searchParams.get('glossary_id')

  let response = {
    name: '',
    data: []
  }

  if (glossaryId === 'glossary001') {
    response = {
      name: 'NLP 术语表',
      data: [
        { en: 'Transformer', zh: '变换器' },
        { en: 'BERT', zh: '双向编码器表示' }
      ]
    }
  } else if (glossaryId === 'glossary002') {
    response = {
      name: '医学图像术语表',
      data: [
        { en: 'MRI', zh: '磁共振成像' },
        { en: 'CT', zh: '计算机断层扫描' }
      ]
    }
  } else {
    response = {
      name: '',
      data: [],
      error: '术语表不存在'
    }
  }

  return response
})

Mock.mock(/\/api\/translate\/status/, 'get', () => {
  return {
    status: 'done',
    url: 'http://localhost:8080/static/fake-translation-result.pdf'
  }
})

Mock.mock(/\/api\/article\/translate/, 'post', () => {
  return {
    id: 'mock-task-001',
    message: '翻译任务已提交'
  }
})

Mock.mock(/\/api\/translate\/.*\/regenerate/, 'post', {
  id: 'translation004',
  date: '2025-04-11 18:45:00',
  path: 'http://localhost:8080/static/fake-translation-result-re.pdf',
  message: '重新翻译成功'
})

// 获取一级评论
Mock.mock(RegExp('/api/getComment1.*'), 'get', {
  comments: [
    {
      comment_id: 'cmt1',
      date: '2025-04-05',
      text: '这篇文章写得很清楚，受益匪浅！',
      like_count: 10,
      username: '用户A',
      user_image: 'https://avatars.githubusercontent.com/u/583231?v=4',
      user_liked: true,
      second_len: 2
    },
    {
      comment_id: 'cmt2',
      date: '2025-04-04',
      text: '请问有没有代码链接？',
      like_count: 2,
      username: '用户B',
      user_image: 'https://avatars.githubusercontent.com/u/810438?v=4',
      user_liked: false,
      second_len: 1
    }
  ]
})

// 获取二级评论
Mock.mock(RegExp('/api/getComment2.*'), 'get', {
  comments: [
    {
      comment_id: 'cmt2-1',
      date: '2025-04-05',
      text: '好像没有代码，不过可以自己实现一下～',
      like_count: 66,
      to_username: '用户B',
      username: '用户C',
      user_image: 'https://avatars.githubusercontent.com/u/583231?v=4',
      user_liked: false
    }
  ]
})

// 点赞/取消点赞评论
Mock.mock('/api/likeComment', 'post', {
  message: '评论点赞成功',
  is_success: true
})

// 模拟保存笔记接口
Mock.mock(/\/api\/saveNote/, 'post', {
  code: 200,
  message: '保存成功'
})

// 模拟获取笔记列表接口
Mock.mock(/\/api\/listNotes/, 'get', {
  code: 200,
  annotations: [
    {
      name: '笔记1',
      annotations: [
        {
          type: 'highlight',
          page: 1,
          rects: [
            { x: 100, y: 150, width: 200, height: 20 }
          ],
          color: '#FFFF00'
        }
      ],
      markdown: '# 笔记1\n\n这是第一条笔记的 Markdown 内容，包含高亮区域说明。'
    },
    {
      name: '笔记2',
      annotations: [
        {
          type: 'text',
          page: 2,
          x: 120,
          y: 300,
          content: '这是注释文本',
          color: '#FF0000'
        }
      ],
      markdown: '# 笔记2\n\n第二条笔记，添加了文字批注。'
    }
  ]
})

// 获取用户对于论文的信息
Mock.mock(RegExp('/api/getUserPaperInfo.*'), 'get', {
  liked: true,
  collected: false,
  score: 4
})

// 获取用户基本信息
Mock.mock('/api/userInfo/userInfo', 'get', {
  user_id: 'u001',
  username: 'Alice',
  avatar: 'https://randomuser.me/api/portraits/women/2.jpg',
  registration_date: '2024-01-01',
  collected_papers_cnt: 5,
  liked_papers_cnt: 12,
  message: '获取成功'
})

// 更新用户头像
Mock.mock('/api/userInfo/avatar', 'post', {
  avatar: 'https://randomuser.me/api/portraits/women/1.jpg',
  message: '头像更新成功'
})

// 获取用户收藏论文列表
Mock.mock('/api/userInfo/collectedPapers', 'get', {
  total: 2,
  papers: [
    {
      paper_id: 'paper001',
      title: '深度学习在医学图像中的应用',
      journal: '人工智能期刊',
      publication_date: '2023-05-10'
    },
    {
      paper_id: 'paper002',
      title: '脑电信号处理综述',
      journal: '神经工程杂志',
      publication_date: '2023-08-22'
    }
  ],
  message: '获取成功'
})

// 获取用户搜索历史
Mock.mock('/api/userInfo/searchHistory', 'get', {
  total: 3,
  keywords: ['医学图像', '脑电信号', '深度学习'],
  message: '获取成功'
})

// 删除搜索记录
Mock.mock('/api/userInfo/delSearchHistory', 'delete', {
  message: '删除成功'
})

// 获取综述报告列表
Mock.mock('/api/userInfo/summaryReports', 'get', {
  total: 1,
  reports: [
    {
      report_id: 'report001',
      title: '图神经网络在社交网络分析中的研究',
      date: '2024-03-20'
    }
  ],
  message: '获取成功'
})

// 删除综述报告
Mock.mock('/api/userInfo/delSummaryReports', 'delete', {
  message: '删除成功'
})

// 获取翻译结果列表
Mock.mock('/api/userInfo/translations', 'get', {
  data: [
    {
      id: 'translation001',
      title: '基于注意力机制的机器翻译研究',
      date: '2024-04-05 15:32:10',
      glossary_name: 'NLP 术语表',
      path: 'http://localhost:8080/static/2023-ICLR-Visual_Classification_via_Description_from_Large_Language_Models.pdf',
      status: 'done'
    },
    {
      id: 'translation002',
      title: '多模态学习在图像文本配对中的应用',
      date: '2024-03-29 10:20:00',
      glossary_name: null,
      path: null,
      status: 'working'
    },
    {
      id: 'translation003',
      title: '语言模型对图像内容的描述能力分析',
      date: '2024-03-20 14:50:00',
      glossary_name: 'Multimodal 术语表',
      path: null,
      status: 'fail'
    }
  ],
  message: '获取翻译结果成功'
})

// 删除翻译结果
Mock.mock(/\/api\/userInfo\/translation(\?.*)?$/, 'delete', (options) => {
  const url = new URL('http://dummy.com' + options.url)
  const translationId = url.searchParams.get('translation_id')

  if (!translationId) {
    return {
      error: '缺少 translation_id 参数'
    }
  }

  return {
    message: '删除翻译结果成功'
  }
})

// 删除收藏论文
Mock.mock('/api/userInfo/delCollectedPapers', 'delete', {
  message: '删除成功'
})

// 获取论文研读记录列表
Mock.mock('/api/userInfo/paperReading', 'get', {
  total: 2,
  paper_reading_list: [
    {
      paper_id: 'paper001',
      title: '深度学习在医学图像中的应用',
      last_read: '2024-04-01'
    },
    {
      paper_id: 'paper002',
      title: '脑电信号处理综述',
      last_read: '2024-04-03'
    }
  ],
  message: '获取成功'
})

// 删除论文研读对话
Mock.mock('/api/userInfo/delPaperReading', 'delete', {
  message: '删除成功'
})

// 获取用户通知
Mock.mock(RegExp('/api/userInfo/notices.*'), 'get', {
  total: 3,
  message: '获取成功'
})

// 设置通知状态已读
Mock.mock('/api/userInfo/readNotices', 'post', {
  message: '已设置为已读'
})

// 删除通知
Mock.mock('/api/userInfo/delNotices', 'delete', {
  message: '删除成功'
})

// 文献推荐 - 热门推荐
Mock.mock('/api/paperRecommend/hot', 'get', {
  papers: [
    {
      paper_id: 'paper001',
      title: '深度学习在图像识别中的应用',
      authors: ['李雷', '韩梅梅'],
      abstract: '本文探讨了深度学习在图像识别领域的应用...',
      publication_date: '2023-09-10',
      citation_count: 123,
      original_url: 'https://example.com/paper001',
      read_count: 1000,
      like_count: 300,
      collect_count: 200,
      comment_count: 50,
      download_count: 500,
      score: 4.7,
      score_count: 80,
      sub_classes: ['人工智能', '图像处理']
    },
    {
      paper_id: 'paper002',
      title: '大语言模型',
      authors: ['James', 'Alice'],
      abstract: '本文探讨了大语言模型...',
      publication_date: '2024-09-10',
      citation_count: 188,
      original_url: 'https://example.com/paper002',
      read_count: 1888,
      like_count: 388,
      collect_count: 288,
      comment_count: 58,
      download_count: 588,
      score: 4.8,
      score_count: 88,
      sub_classes: ['大模型']
    },
    {
      paper_id: 'paper003',
      title: 'Transformer架构综述',
      authors: ['张三', '李四'],
      abstract: '本文系统回顾了Transformer模型的发展与应用...',
      publication_date: '2022-05-21',
      citation_count: 256,
      original_url: 'https://example.com/paper003',
      read_count: 2100,
      like_count: 520,
      collect_count: 400,
      comment_count: 65,
      download_count: 700,
      score: 4.9,
      score_count: 100,
      sub_classes: ['自然语言处理', '模型架构']
    },
    {
      paper_id: 'paper004',
      title: '图神经网络在推荐系统中的应用',
      authors: ['王五'],
      abstract: '本文介绍了图神经网络在推荐系统中的最新进展...',
      publication_date: '2023-11-18',
      citation_count: 132,
      original_url: 'https://example.com/paper004',
      read_count: 980,
      like_count: 260,
      collect_count: 180,
      comment_count: 40,
      download_count: 420,
      score: 4.5,
      score_count: 76,
      sub_classes: ['推荐系统', '图神经网络']
    },
    {
      paper_id: 'paper005',
      title: '跨模态检索技术研究',
      authors: ['赵六', '田七'],
      abstract: '本文综述了跨模态检索的核心技术和未来方向...',
      publication_date: '2021-08-15',
      citation_count: 198,
      original_url: 'https://example.com/paper005',
      read_count: 1750,
      like_count: 430,
      collect_count: 300,
      comment_count: 55,
      download_count: 630,
      score: 4.6,
      score_count: 83,
      sub_classes: ['多模态学习', '信息检索']
    },
    {
      paper_id: 'paper006',
      title: '自监督学习最新进展',
      authors: ['孙八'],
      abstract: '本文综述了自监督学习的关键方法与挑战...',
      publication_date: '2022-12-20',
      citation_count: 143,
      original_url: 'https://example.com/paper006',
      read_count: 1600,
      like_count: 350,
      collect_count: 240,
      comment_count: 48,
      download_count: 520,
      score: 4.4,
      score_count: 70,
      sub_classes: ['自监督学习', '机器学习']
    },
    {
      paper_id: 'paper007',
      title: '可解释人工智能的发展现状',
      authors: ['周九', '吴十'],
      abstract: '本文分析了可解释人工智能的研究动机与方法...',
      publication_date: '2023-03-02',
      citation_count: 111,
      original_url: 'https://example.com/paper007',
      read_count: 1350,
      like_count: 290,
      collect_count: 210,
      comment_count: 44,
      download_count: 480,
      score: 4.3,
      score_count: 65,
      sub_classes: ['人工智能', '可解释性']
    },
    {
      paper_id: 'paper008',
      title: '多模态学习在医学图像分析中的应用',
      authors: ['钱十一'],
      abstract: '本文探讨了多模态学习技术在医学图像分析中的前景...',
      publication_date: '2024-01-25',
      citation_count: 172,
      original_url: 'https://example.com/paper008',
      read_count: 2000,
      like_count: 410,
      collect_count: 310,
      comment_count: 60,
      download_count: 600,
      score: 4.7,
      score_count: 85,
      sub_classes: ['多模态学习', '医学图像']
    },
    {
      paper_id: 'paper009',
      title: '生成模型的对抗训练方法',
      authors: ['郑十二'],
      abstract: '本文介绍了GAN训练中面临的问题与对策...',
      publication_date: '2022-07-07',
      citation_count: 199,
      original_url: 'https://example.com/paper009',
      read_count: 1480,
      like_count: 340,
      collect_count: 230,
      comment_count: 53,
      download_count: 570,
      score: 4.6,
      score_count: 79,
      sub_classes: ['生成模型', '对抗训练']
    },
    {
      paper_id: 'paper010',
      title: '视觉语言模型的融合策略',
      authors: ['刘十三', '陈十四'],
      abstract: '本文分析了视觉与语言融合模型的主流技术...',
      publication_date: '2023-10-05',
      citation_count: 165,
      original_url: 'https://example.com/paper010',
      read_count: 1920,
      like_count: 390,
      collect_count: 280,
      comment_count: 57,
      download_count: 590,
      score: 4.8,
      score_count: 91,
      sub_classes: ['视觉语言', '多模态模型']
    }
  ]
})

// 个性化文献推荐
Mock.mock('/api/paperRecommend/personalized', 'get', {
  papers: [
    {
      paper_id: 'paper101',
      title: '强化学习在推荐系统中的新进展',
      authors: ['张伟', '王芳'],
      abstract: '本文深入探讨了强化学习在个性化推荐中的应用与挑战...',
      publication_date: '2024-03-15',
      citation_count: 98,
      original_url: 'https://example.com/paper101',
      read_count: 860,
      like_count: 240,
      collect_count: 130,
      comment_count: 35,
      download_count: 410,
      score: 4.6,
      score_count: 76,
      sub_classes: ['推荐系统', '强化学习'],
      reason: '你最近阅读了多篇关于推荐系统的论文'
    },
    {
      paper_id: 'paper102',
      title: '联邦学习在隐私保护中的应用研究',
      authors: ['Chen Yu', 'Liu Mei'],
      abstract: '随着数据隐私问题的加剧，联邦学习成为解决方案之一...',
      publication_date: '2023-12-01',
      citation_count: 150,
      original_url: 'https://example.com/paper102',
      read_count: 1300,
      like_count: 310,
      collect_count: 190,
      comment_count: 42,
      download_count: 520,
      score: 4.9,
      score_count: 102,
      sub_classes: ['隐私计算', '联邦学习'],
      reason: '你收藏的论文中涉及隐私保护的较多'
    },
    {
      paper_id: 'paper103',
      title: '图神经网络（GNN）综述与前沿探索',
      authors: ['Alice Zhang', '李想'],
      abstract: '本综述系统梳理了GNN的发展脉络和最新研究趋势...',
      publication_date: '2024-02-20',
      citation_count: 110,
      original_url: 'https://example.com/paper103',
      read_count: 920,
      like_count: 280,
      collect_count: 160,
      comment_count: 37,
      download_count: 460,
      score: 4.7,
      score_count: 89,
      sub_classes: ['图神经网络', '深度学习'],
      reason: '你对图结构建模表现出高度兴趣'
    },
    {
      paper_id: 'paper104',
      title: '大语言模型在多模态任务中的新进展',
      authors: ['王立', '赵敏'],
      abstract: '探讨大语言模型如何与图像、音频等模态结合完成复杂任务...',
      publication_date: '2024-01-05',
      citation_count: 76,
      original_url: 'https://example.com/paper104',
      read_count: 670,
      like_count: 200,
      collect_count: 110,
      comment_count: 21,
      download_count: 300,
      score: 4.5,
      score_count: 61,
      sub_classes: ['多模态学习', '大语言模型'],
      reason: '你最近搜索了关于多模态的内容'
    },
    {
      paper_id: 'paper105',
      title: '知识图谱驱动的问答系统研究',
      authors: ['刘强', '杨雪'],
      abstract: '本研究结合知识图谱与自然语言处理技术提升问答系统效果...',
      publication_date: '2023-10-28',
      citation_count: 132,
      original_url: 'https://example.com/paper105',
      read_count: 1100,
      like_count: 290,
      collect_count: 170,
      comment_count: 48,
      download_count: 490,
      score: 4.8,
      score_count: 94,
      sub_classes: ['知识图谱', '问答系统'],
      reason: '你曾深入阅读关于问答系统的综述'
    },
    {
      paper_id: 'paper106',
      title: '对抗样本与模型鲁棒性研究综述',
      authors: ['李晨', '吴婷'],
      abstract: '本综述梳理了对抗攻击与防御方法的演进及其在实际中的挑战...',
      publication_date: '2024-02-11',
      citation_count: 85,
      original_url: 'https://example.com/paper106',
      read_count: 780,
      like_count: 230,
      collect_count: 140,
      comment_count: 30,
      download_count: 370,
      score: 4.4,
      score_count: 72,
      sub_classes: ['对抗学习', '模型鲁棒性'],
      reason: '你最近关注了模型安全性相关文献'
    },
    {
      paper_id: 'paper107',
      title: '基于Transformer的时间序列建模研究',
      authors: ['Zhou Lin', 'Ma Qian'],
      abstract: '探索Transformer结构在时间序列预测中的优势与挑战...',
      publication_date: '2024-04-02',
      citation_count: 59,
      original_url: 'https://example.com/paper107',
      read_count: 620,
      like_count: 190,
      collect_count: 90,
      comment_count: 18,
      download_count: 290,
      score: 4.3,
      score_count: 58,
      sub_classes: ['时间序列', 'Transformer'],
      reason: '你多次查阅时间序列预测相关主题'
    },
    {
      paper_id: 'paper108',
      title: '自监督学习在医学影像分析中的应用',
      authors: ['何琳', '高飞'],
      abstract: '介绍自监督学习方法在医学影像识别、分割等方面的应用进展...',
      publication_date: '2023-11-18',
      citation_count: 120,
      original_url: 'https://example.com/paper108',
      read_count: 980,
      like_count: 260,
      collect_count: 150,
      comment_count: 39,
      download_count: 430,
      score: 4.7,
      score_count: 83,
      sub_classes: ['自监督学习', '医学图像'],
      reason: '你经常浏览医学图像处理相关论文'
    }
  ]
})

// 记录每个 recordId 的轮询次数
const pollCounts = {}

// 1. 启动检索
Mock.mock('/api/v2/search/vectorQuery', 'post', {
  code: 200,
  message: '启动检索成功',
  data: {
    search_record_id: 'record123'
  }
})

// 2. 轮询状态：前两次 hint，第三次 success
Mock.mock(/\/api\/v2\/search\/status\?search_record_id=.+/, 'get', (options) => {
  const url = options.url
  const recordId = url.match(/search_record_id=(.+)/)[1]

  console.log('[Mock] 接收到状态轮询请求，recordId:', recordId)

  if (pollCounts[recordId] == null) {
    pollCounts[recordId] = 0
  }
  pollCounts[recordId]++

  if (pollCounts[recordId] < 8) {
    console.log('[Mock] 返回 hint 状态，第', pollCounts[recordId], '步')
    return {
      code: 200,
      data: {
        type: 'hint',
        content: `AI 正在思考...（第 ${pollCounts[recordId]} 步）`
      }
    }
  } else {
    console.log('[Mock] 返回 success 状态')
    return {
      code: 200,
      data: {
        type: 'success'
      }
    }
  }
})

// 3. 获取结果
Mock.mock(/\/api\/v2\/search\/result\?search_record_id=.+/, 'get', {
  code: 200,
  data: {
    paper_infos: [
      {
        paper_id: 'paper001',
        title: '基于注意力机制的图像分类方法综述',
        authors: ['李雷', '韩梅梅'],
        abstract: '本文总结了注意力机制在图像分类中的应用与发展...',
        publication_date: '2021-05-12',
        citation_count: 120,
        original_url: 'https://example.com/paper001',
        read_count: 960,
        like_count: 310,
        collect_count: 200,
        comment_count: 45,
        download_count: 400,
        score: 4.6,
        score_count: 75,
        sub_classes: ['计算机视觉']
      },
      {
        paper_id: 'paper002',
        title: 'Transformer模型综述',
        authors: ['王五'],
        abstract: '本文综述了Transformer模型的结构与应用...',
        publication_date: '2022-06-15',
        citation_count: 85,
        original_url: 'https://example.com/paper002',
        read_count: 800,
        like_count: 220,
        collect_count: 150,
        comment_count: 40,
        download_count: 300,
        score: 4.5,
        score_count: 60,
        sub_classes: ['自然语言处理']
      },
      {
        paper_id: 'paper003',
        title: '多模态学习在医疗诊断中的应用',
        authors: ['张伟'],
        abstract: '介绍多模态数据融合技术在医学图像分析中的应用...',
        publication_date: '2020-10-08',
        citation_count: 95,
        original_url: 'https://example.com/paper003',
        read_count: 720,
        like_count: 180,
        collect_count: 130,
        comment_count: 35,
        download_count: 290,
        score: 4.3,
        score_count: 55,
        sub_classes: ['多模态学习', '医疗AI']
      },
      {
        paper_id: 'paper004',
        title: '大语言模型的可解释性研究',
        authors: ['赵六'],
        abstract: '探讨当前主流语言模型的可解释性分析方法...',
        publication_date: '2023-02-28',
        citation_count: 50,
        original_url: 'https://example.com/paper004',
        read_count: 640,
        like_count: 160,
        collect_count: 110,
        comment_count: 28,
        download_count: 250,
        score: 4.2,
        score_count: 48,
        sub_classes: ['自然语言处理', '模型可解释性']
      },
      {
        paper_id: 'paper005',
        title: '图神经网络在推荐系统中的应用',
        authors: ['孙七'],
        abstract: '本文介绍了GNN在推荐系统中的最新研究成果...',
        publication_date: '2022-11-10',
        citation_count: 60,
        original_url: 'https://example.com/paper005',
        read_count: 700,
        like_count: 190,
        collect_count: 140,
        comment_count: 32,
        download_count: 280,
        score: 4.4,
        score_count: 58,
        sub_classes: ['图神经网络', '推荐系统']
      },
      {
        paper_id: 'paper006',
        title: '自监督学习最新进展综述',
        authors: ['周八'],
        abstract: '本文综述了自监督学习领域的主流方法与应用...',
        publication_date: '2021-08-20',
        citation_count: 130,
        original_url: 'https://example.com/paper006',
        read_count: 890,
        like_count: 260,
        collect_count: 180,
        comment_count: 38,
        download_count: 330,
        score: 4.7,
        score_count: 80,
        sub_classes: ['机器学习']
      },
      {
        paper_id: 'paper007',
        title: 'CLIP模型在视觉语言任务中的应用',
        authors: ['钱九'],
        abstract: '分析CLIP模型在图文检索、图文匹配中的表现...',
        publication_date: '2023-01-05',
        citation_count: 110,
        original_url: 'https://example.com/paper007',
        read_count: 770,
        like_count: 240,
        collect_count: 170,
        comment_count: 36,
        download_count: 310,
        score: 4.6,
        score_count: 70,
        sub_classes: ['视觉语言模型']
      },
      {
        paper_id: 'paper008',
        title: '少样本学习综述：挑战与进展',
        authors: ['吴十'],
        abstract: '少样本学习面临数据稀缺问题，本文综述了应对策略...',
        publication_date: '2020-03-18',
        citation_count: 150,
        original_url: 'https://example.com/paper008',
        read_count: 950,
        like_count: 300,
        collect_count: 210,
        comment_count: 50,
        download_count: 370,
        score: 4.8,
        score_count: 90,
        sub_classes: ['元学习', '少样本学习']
      },
      {
        paper_id: 'paper009',
        title: '跨模态检索中的对齐方法研究',
        authors: ['郑一'],
        abstract: '本文探讨了图像与文本之间的语义对齐策略...',
        publication_date: '2021-12-22',
        citation_count: 70,
        original_url: 'https://example.com/paper009',
        read_count: 680,
        like_count: 170,
        collect_count: 125,
        comment_count: 30,
        download_count: 260,
        score: 4.1,
        score_count: 45,
        sub_classes: ['多模态学习']
      },
      {
        paper_id: 'paper010',
        title: '强化学习在智能体决策中的应用综述',
        authors: ['冯十一'],
        abstract: '综述了强化学习在游戏、自动驾驶等领域的应用进展...',
        publication_date: '2022-04-01',
        citation_count: 100,
        original_url: 'https://example.com/paper010',
        read_count: 820,
        like_count: 210,
        collect_count: 160,
        comment_count: 42,
        download_count: 295,
        score: 4.5,
        score_count: 65,
        sub_classes: ['强化学习']
      }
    ],
    ai_reply: '这是与您的检索内容最相关的论文。',
    keywords: ['深度学习', '多模态', '自然语言处理'],
    search_record_id: 'record123'
  }
})

// 对话式检索
Mock.mock('/api/search/dialogQuery', 'post', {
  dialog_type: '总结',
  papers: [
    {
      paper_id: 'paper003',
      title: '图神经网络研究进展',
      authors: ['赵六'],
      abstract: '介绍了图神经网络的发展与挑战...',
      publication_date: '2021-12-01',
      citation_count: 60,
      original_url: 'https://example.com/paper003',
      read_count: 600,
      like_count: 180,
      collect_count: 100,
      comment_count: 30,
      download_count: 250,
      score: 4.3,
      score_count: 45,
      sub_classes: ['图神经网络']
    }
  ],
  content: '以下是关于图神经网络的一些总结内容...'
})

// 删除对话式检索记录
Mock.mock(/\/api\/search\/flush/, 'delete', {})

// 获取综述生成状态
Mock.mock(/\/api\/summary\/getSummaryStatus/, 'get', {
  status: 'completed'
})

// 生成综述报告
Mock.mock('/api/summary/generateSummaryReport', 'post', {
  message: '综述报告生成成功',
  report_id: 'report123'
})

// 简单语义检索（无返回值）
Mock.mock('/api/search/easyVectorQuery', 'post', {})

// 恢复检索记录
Mock.mock(/\/api\/search\/restoreSearchRecord/, 'get', {
  conversation: ['你好，请推荐关于Transformer的论文。', '以下是相关论文...'],
  paper_infos: [
    {
      paper_id: 'paper004',
      title: 'BERT模型详解',
      authors: ['张三'],
      abstract: 'BERT是基于Transformer的预训练语言模型...',
      publication_date: '2020-03-10',
      citation_count: 300,
      original_url: 'https://example.com/paper004',
      read_count: 1200,
      like_count: 400,
      collect_count: 280,
      comment_count: 90,
      download_count: 700,
      score: 4.8,
      score_count: 100,
      sub_classes: ['语言模型']
    }
  ],
  message: '恢复成功'
})

// 获取语义检索历史
Mock.mock('/api/study/getUserSearchHistory', 'get', {
  keywords: ['BERT', '图神经网络', '深度学习'],
  message: '获取成功'
})

// 生成知识库
Mock.mock('/api/search/rebuildKB', 'post', {
  kb_id: 'kb456'
})

// 获取所有批注（包含段落 + 评论）
Mock.mock(/\/paper\/annotations\?paper_id=\w+/, 'get', () => {
  return {
    code: 200,
    data: [
      {
        passage_content: '本段介绍了视觉语言模型在零样本图像分类中的潜力。',
        comments: [
          {
            id: 'comment-001',
            content: '我认为这段描述很清晰，适合放在引言部分。',
            author_name: '张三',
            author_avatar: 'https://randomuser.me/api/portraits/men/1.jpg',
            liked: true,
            replies: []
          },
          {
            id: 'comment-002',
            content: '可以补充一些具体模型的名称吗？',
            author_name: '李四',
            author_avatar: 'https://randomuser.me/api/portraits/women/1.jpg',
            liked: false,
            replies: []
          }
        ]
      },
      {
        passage_content: '作者使用了CLIP模型来验证分类效果，作者使用了CLIP模型来验证分类效果，作者使用了CLIP模型来验证分类效果，作者使用了CLIP模型来验证分类效果，作者使用了CLIP模型来验证分类效果。',
        comments: [
          {
            id: 'comment-003',
            content: '这里是否可以加入实验设置的细节？',
            author_name: '王五',
            author_avatar: 'https://randomuser.me/api/portraits/men/3.jpg',
            liked: false,
            replies: []
          }
        ]
      }
    ]
  }
})

// 添加段落+批注
Mock.mock(/\/paper\/annotation\?paper_id=\w+/, 'put', () => {
  return {
    code: 200,
    data: {
      id: 'comment-999'
    }
  }
})

// 点赞/取消点赞
Mock.mock(/\/paper\/annotation\/comments\/like\/toggle\?annotation_id=\w+/, 'post', () => {
  return {
    code: 200,
    message: '点赞状态已切换'
  }
})

// 添加评论回复
Mock.mock(/\/paper\/annotation\/comment\?annotation_id=\w+/, 'put', () => {
  return {
    code: 200,
    message: '评论已添加'
  }
})

// 获取评论的回复
Mock.mock(/\/paper\/annotation\/comments\?annotation_id=comment-001/, 'get', () => {
  return {
    code: 200,
    data: [
      {
        content: '我也有同感。',
        author: '赵六'
      },
      {
        content: '这段是原文中的精华部分。',
        author: '钱七'
      }
    ]
  }
})

// 其他评论暂无回复
Mock.mock(/\/paper\/annotation\/comments\?annotation_id=\w+/, 'get', () => {
  return {
    code: 200,
    data: []
  }
})

// 论文循证
Mock.mock('/api/search/changeRecordPapers', 'post', {
  msg: '记录修改成功'
})

// 上传文件
Mock.mock('/api/uploadPaper', 'post', {
  message: '上传成功',
  file_id: 'file001',
  file_url: 'https://arxiv.org/pdf/2403.00123.pdf',
  is_success: true
})

// 获取上传文件列表
Mock.mock('/api/userInfo/documents', 'get', {
  total: 2,
  documents: [
    {
      document_id: 'file001',
      name: 'Transformer综述.pdf',
      upload_time: '2024-03-01 10:30:00',
      file_url: 'https://arxiv.org/pdf/2403.00123.pdf'
    },
    {
      document_id: 'file002',
      name: '图神经网络研究.pdf',
      upload_time: '2024-03-05 14:00:00',
      file_url: 'https://arxiv.org/pdf/2403.00123.pdf'
    }
  ],
  message: '获取成功'
})

// 删除已上传文献
Mock.mock('/api/removeUploadedPaper', 'post', {
  message: '删除成功',
  is_success: true
})

// 获取文档URL（无返回值）
Mock.mock(/\/api\/getDocumentURL/, 'get', {})

// mock/api/study.js

// 初始化语义检索向量库
Mock.mock('/api/init/localVDBInit', 'get', {})

// 创建文献研读
Mock.mock('/api/study/createPaperStudy', 'post', {
  file_reading_id: 'read001',
  conversation_history: ['系统初始化完毕，欢迎开始研读。'],
  message: '创建成功'
})

// 恢复文献研读
Mock.mock('/api/study/restorePaperStudy', 'post', {
  file_reading_id: 'read001',
  conversation_history: ['用户：这篇文章的创新点是什么？', 'AI：主要创新在于提出了一个新的编码结构。'],
  message: '恢复成功'
})

// 进行文献研读
Mock.mock('/api/study/doPaperStudy', 'post', {
  ai_reply: '本文主要研究图神经网络的表示能力。',
  docs: ['第1页：介绍图神经网络的基本概念', '第2页：提出了新的GNN结构'],
  prob_question: ['这篇文章的方法和GCN有何不同？'],
  message: '回答成功'
})

// 单篇摘要生成
Mock.mock('/api/study/generateAbstractReport', 'post', {
  summary: '本研究提出了一种新型图神经网络模型，能够有效捕捉节点间的结构关系...'
})

// 获取论文PDF
Mock.mock(/\/api\/study\/getPaperPDF/, 'get', {
  local_url: 'https://arxiv.org/pdf/2403.00123.pdf',
  message: '获取成功'
})

// 重新生成文献研读回答（无返回值）
Mock.mock('/api/study/reDoPaperStudy', 'post', {})

// 清除文献研读对话（无返回值）
Mock.mock('/api/study/clearConversation', 'post', {})

// 向量化嵌入
Mock.mock('/other/embed_texts', 'post', {})

// 创建单个知识库
Mock.mock('/knowledge_base/create_knowledge_base', 'post', {
  code: 200,
  msg: '知识库创建成功',
  data: {
    knowledge_base_id: 'kb_001'
  }
})

// 知识库上传文件
Mock.mock('/knowledge_base/upload_docs', 'post', {
  code: 200,
  msg: '文件上传成功',
  data: {
    uploaded_files: ['doc1.pdf', 'doc2.pdf']
  }
})

// 创建临时知识库
Mock.mock('/knowledge_base/upload_temp_docs', 'post', {
  code: 200,
  msg: '临时知识库创建成功',
  data: {
    temp_kb_id: 'temp_kb_001'
  }
})

// 删除知识库
Mock.mock('/knowledge_base/delete_knowledge_base', 'post', {})

// 重建知识库（重新向量化）
Mock.mock('/knowledge_base/recreate_vector_store', 'post', {})

// 知识库检索
Mock.mock('/knowledge_base/search_docs', 'post', {
  page_content: '这是文档内容的一部分',
  metadata: {
    author: '张三',
    date: '2023-11-10'
  },
  type: 'pdf',
  id: 'doc123',
  score: 0.93
})

// 与临时知识库对话
Mock.mock('/chat/file_chat', 'post', {})

// 摘要生成
Mock.mock('/knowledge_base/kb_summary_api/summary_file_to_vector_store', 'post', {})

// 获取知识库内文件
Mock.mock(/\/knowledge_base\/list_files/, 'get', {
  code: 200,
  msg: '文件列表获取成功',
  data: [
    { file_name: '论文1.pdf', upload_date: '2024-04-01' },
    { file_name: '报告2.docx', upload_date: '2024-04-03' }
  ]
})

// 大模型对话
Mock.mock('/chat/chat', 'post', {})

// 删除临时向量库
Mock.mock('/knowledge_base/delete_temp_docs', 'post', {})
