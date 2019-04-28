from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth import authenticate
from manager.models import UserAccount, Project

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as AuthLoginView
from django.contrib.auth.views import LogoutView as AuthLogoutView
from django.contrib.sites.shortcuts import get_current_site
from django.core.signing import BadSignature, SignatureExpired, loads, dumps
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.loader import get_template
from django.views import generic
from .forms import (
    LoginForm, UserCreateForm, ProjectSearchForm
)
from django.db.models import Q
from django.views.decorators.csrf import csrf_protect

import operator
from functools import reduce

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


User = get_user_model()
# Create your views here.

class AccountListView(TemplateView):
    template_name = "index.html"

    def get(self, request, *args, **kwargs):
        context = super(AccountListView, self).get_context_data(**kwargs)
        return render(self.request, self.template_name, context)
    
    def post(self, _, *args, **kwargs):
        username = self.request.POST['username']
        password = self.request.POST['password']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(self.request, user)
            return redirect(self.get_next_redirect_url())
        else:
            kwargs = {'template_name': 'login.html'}
            return login(self.request, *args, **kwargs)

    def get_next_redirect_url(self):
        redirect_url = self.request.GET.get('next')
        if not redirect_url or redirect_url == '/':
            redirect_url = '/worker_list/'
        return redirect_url

class LoginView(AuthLoginView):
    template_name = 'manager/index.html'


class LogoutView(LoginRequiredMixin, AuthLogoutView):
    template_name = 'manager/logout.html'


class UserCreate(generic.CreateView):
    """ユーザー仮登録"""
    template_name = 'user_create.html'
    form_class = UserCreateForm

    def form_valid(self, form):
        """仮登録と本登録用メールの発行."""
        # 仮登録と本登録の切り替えは、is_active属性を使うと簡単です。
        # 退会処理も、is_activeをFalseにするだけにしておくと捗ります。
        user = form.save(commit=False)
        user.is_active = False
        user.save()

        # アクティベーションURLの送付
        current_site = get_current_site(self.request)
        domain = current_site.domain
        context = {
            'protocol': self.request.scheme,
            'domain': domain,
            'token': dumps(user.pk),
            'user': user,
        }

        subject_template = get_template('manager/mail_templates/user_create/subject.txt')
        subject = subject_template.render(context)

        message_template = get_template('manager/mail_templates/user_create/message.txt')
        message = message_template.render(context)

        user.email_user(subject, message)
        return redirect('manager:user_create_done')


class UserCreateDone(generic.TemplateView):
    """ユーザー仮登録したよ"""
    template_name = 'user_create_done.html'


class UserCreateComplete(generic.TemplateView):
    """メール内URLアクセス後のユーザー本登録"""
    template_name = 'user_create_complete.html'
    timeout_seconds = getattr(settings, 'ACTIVATION_TIMEOUT_SECONDS', 60*60*3)  # デフォルトでは3h以内

    def get(self, request, **kwargs):
        """tokenが正しければ本登録."""
        token = kwargs.get('token')
        try:
            user_pk = loads(token, max_age=self.timeout_seconds)

        # 期限切れ
        except SignatureExpired:
            return HttpResponseBadRequest()

        # tokenが間違っている
        except BadSignature:
            return HttpResponseBadRequest()

        # tokenは問題なし
        else:
            try:
                user = User.objects.get(pk=user_pk)
            except User.DoesNotExist:
                return HttpResponseBadRequest()
            else:
                if not user.is_active:
                    # 問題なければ本登録とする
                    user.is_active = True
                    user.save()
                    return super().get(request, **kwargs)

        return HttpResponseBadRequest()

class ProjectIndex(generic.ListView):
    model = Project
    paginate_by = 10

def paginate_queryset(request, queryset, count):
    """return a page object"""
    paginator = Paginator(queryset, count)
    page = request.GET.get('page')
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj

@csrf_protect
def project_search(request):
    """Search Projects"""
    # create an empty form
    form = ProjectSearchForm()
    # fetch all data of projects
    projects = Project.objects.all()
    # When the search button is pushed
    if request.method == 'POST':
        # fetch the form data
        form = ProjectSearchForm(request.POST)
        projects = Project.objects.all()
        if form.is_valid():
            # split the inputed data into keywords
            keywords = form.cleaned_data['keyword'].split()
            # make query from keywords: "and" combination of (keyword1 in name or details)
            query = reduce(operator.and_, ((Q(name__contains=keyword)|Q(details__contains=keyword)) for keyword in keywords))
            # fetch the project data with the query
            projects = Project.objects.filter(query)
    # paging
    page_obj = paginate_queryset(request, projects, ProjectIndex.paginate_by)
    # generate the context
    context = {
        'form':form,
        'page_obj':page_obj,
    }
    # render project_search.html with the fetched project data
    return render(request,
                  'project_search.html',
                  context)
    