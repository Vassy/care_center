# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['care_center.base', 'project.task']

    phonecall_ids = fields.One2many(
        comodel_name='crm.phonecall',
        inverse_name='task_id',
        string='Phonecalls',
    )
    phonecall_count = fields.Integer(
        compute='_phonecall_count',
        string="Phonecalls",
    )
    convertable = fields.Boolean(compute='_can_be_converted')

    @api.multi
    def _can_be_converted(self):
        for task in self:
            convertable = True
            if not task.active:
                convertable = False
            elif len(task.timesheet_ids):
                convertable = False
            elif task.stage_id.fold:
                convertable = False
            task.convertable = convertable

    @api.multi
    def _phonecall_count(self):
        for task in self:
            task.phonecall_count = self.env['crm.phonecall'].search_count(
                [('task_id', '=', task.id)],
            )

    def get_tag_ids(self):
        """
        When converting Task to Opportunity, carry Tags over if name is exact match
        """
        if not self.tag_ids:
            return []
        tag_names = self.tag_ids.mapped('name')
        return self.env['crm.lead.tag'].search([('name', 'in', tag_names)]).mapped('id')

    def get_team_id(self):
        """
        When converting Task to Opportunity, carry Team over,
        if Suffix is Support instead of Sales
        """
        if not self.team_id:
            return False
        name = self.team_id.name
        if name.lower().endswith('support'):
            name = name[:7].strip()
        team = self.env['crm.team'].search([
            '|',
            ('name', '=', name),
            ('name', '=', '%s Sales' % name),
        ], limit=1)
        return team and team.id

    def move_phonecalls(self, opportunity_id):
        task_calls = self.env['crm.phonecall'].search([(
            'task_id', '=', self.id,
        )])
        task_calls.write({
            'task_id': False,
            'opportunity_id': opportunity_id,
        })

    def move_attachments(self, opportunity_id):
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'project.task'),
            ('res_id', '=', self.id),
        ])
        attachments.write({
            'res_model': 'crm.lead',
            'res_id': opportunity_id,
        })

    @api.multi
    def convert_to_opportunity(self):
        """
        Tasks may get created prematurely, or from emails sent to the incorrect alias.
        Helper function to convert such Tasks to Opportunities.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError('Please specify a Customer before converting to Opportunity.')

        if self.timesheet_ids:
            raise UserError('Cannot convert to Opportunity after Timesheets are assigned.')

        opportunity = self.env['crm.lead'].create({
            'name': self.name,
            'planned_revenue': 0.0,
            'probability': 0.0,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id and self.user_id.id,
            'team_id': self.get_team_id(),
            'description': self.description,
            'priority': self.priority,
            'type': 'opportunity',
            'phone': self.partner_id.phone,
            'email_from': self.partner_id.email,
            'medium_id': self.medium_id and self.medium_id.id,
            'tag_ids': [(6, 0, self.get_tag_ids())]
        })
        opportunity._onchange_partner_id()
        self.move_phonecalls(opportunity_id=opportunity.id)
        self.move_attachments(opportunity_id=opportunity.id)
        self.message_change_thread(opportunity)
        self.write({'active': False})

        return {
            'name': 'Convert Task to Opportunity',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': self.env.ref('crm.crm_case_form_view_oppor').id,
            'res_model': 'crm.lead',
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'current',
            'res_id': opportunity.id,
        }
