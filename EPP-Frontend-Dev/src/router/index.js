import Vue from 'vue'
import Router from 'vue-router'
import HelloWorld from '@/components/HelloWorld'
import About from '@/components/About'

import Dashboard from '@/components/Main/Dashboard'
import SearchPage from '@/components/Search/SearchPage'
import SearchResult from '@/components/Search/SearchResult'
import PaperInfo from '@/components/PaperInfo/PaperInfo'
import PersonalMain from '@/components/Personal/PersonalMain'
import uploadDocuMain from '@/components/UploadDocuments/UploadDocuMain'
import ResearchAgentHome from '@/views/ResearchAgent/ResearchAgentHome'
import ResearchAgentSession from '@/views/ResearchAgent/ResearchAgentSession'
import PaperReader from '@/components/PaperRead/PaperReader'
import LocalPaperReader from '@/components/PaperRead/LocalPaperReader'
import PdfAnnotations from '@/components/PaperRead/PdfAnnotations'
// import message from 'element-ui'

// import { userVisitRecord } from '../request/userRequest'

Vue.use(Router)

const router = new Router({
  routes: [
    {
      path: '/',
      name: 'HelloWorld',
      redirect: '/dashboard',
      component: HelloWorld,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/aboutus',
      name: 'aboutus',
      component: About,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: Dashboard,
      meta: {
        hideNavbar: true // 标识不显示导航栏
      }
    },
    {
      path: '/search',
      name: 'search',
      component: SearchPage,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/search/results',
      name: 'search-results',
      component: SearchResult,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/paper/info/:paper_id',
      name: 'paper-info',
      component: PaperInfo,
      props: true,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/paper/reader/:paper_id',
      name: 'paper-reader',
      component: PaperReader,
      props: true,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/paper/annotations/:paper_id',
      name: 'paper-annotaions',
      component: PdfAnnotations,
      props: true,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/paper/localReader/:paper_id',
      name: 'localPaper-reader',
      component: LocalPaperReader,
      props: true,
      meta: {
        hideNavbar: false// 标识显示导航栏
      }
    },
    {
      path: '/personal',
      name: 'personal',
      component: PersonalMain,
      props: true,
      meta: {
        hideNavbar: false// 标识不显示导航栏
      }
    },
    {
      path: '/upload',
      name: 'uploadDocuMain',
      component: uploadDocuMain,
      props: true,
      meta: {
        hideNavbar: false
      }
    },
    {
      path: '/research-agent',
      name: 'ResearchAgentHome',
      component: ResearchAgentHome,
      meta: {
        hideNavbar: true
      }
    },
    {
      path: '/research-agent/session/:sessionId',
      name: 'ResearchAgentSession',
      component: ResearchAgentSession,
      props: true,
      meta: {
        hideNavbar: true
      }
    }
  ]
})

// 获取 Cookie 的帮助函数
// function getCookie (name) {
//   const value = `; ${document.cookie}`
//   const parts = value.split(`; ${name}=`)
//   if (parts.length === 2) return parts.pop().split(';').shift()
// }

// router.beforeEach((to, from, next) => {
//   const sessionID = getCookie('userlogin')
//   if (!sessionID) {
//     if (to.path !== '/dashboard') {
//       message.Message({
//         type: 'error',
//         message: '未登录或登录过期，请重新登录！'
//       })
//       next('/dashboard')
//     } else {
//       next()
//     }
//   } else if (to.path === '/' || to.path === '/dashboard') {
//     userVisitRecord() // 用户访问登记
//     next('/search')
//   } else {
//     userVisitRecord() // 用户访问登记
//     next()
//   }
// })

export default router
